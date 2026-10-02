"""Endpoints de la tienda como clases `APIView`.

Convenciones del módulo:
- Las vistas que manejan datos del usuario (carrito, tarjetas, órdenes) acotan sus
  consultas al `request.user`. Las excepciones son deliberadas: `LoginView`,
  `ConfigView` y `ProductListView` son públicas, y `WebhookView` localiza la orden
  por `mp_order_id` porque MP no envía credenciales de usuario.
- Las mutaciones del carrito terminan devolviendo el carrito completo, reutilizando
  `CartView.get`, para que el cliente no necesite un segundo fetch.
- El importe de un pago SIEMPRE se recalcula aquí desde el carrito persistido; el
  cliente nunca decide cuánto se cobra.
"""

import json
import re
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import mp
from .models import CartItem, Order, OrderItem, Product, SavedCard
from .serializers import (
    CartItemSerializer,
    OrderSerializer,
    ProductSerializer,
    SavedCardSerializer,
)

User = get_user_model()

#: Único patrón de email aceptado en el login (atajo de pruebas, no validación real).
TEST_EMAIL_RE = re.compile(r"^test_payer_\d{1,10}@testuser\.com$")


def mp_error_response(exc: mp.MPError):
    """Traduce un `MPError` a un 502 conservando el cuerpo original de MP.

    Se usa para que la UI muestre el motivo real del rechazo en lugar de un
    error genérico; `errorMessage()` en el frontend lo extrae de `data.mp`.
    """
    return Response(
        {
            "detail": "Error de Mercado Pago",
            "mp_status": exc.status_code,
            "mp": exc.body,
        },
        status=status.HTTP_502_BAD_GATEWAY,
    )


# ---------- Auth / config ----------
class LoginView(APIView):
    """Login simplificado SOLO PARA PRUEBAS: crea/obtiene un usuario por email."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Inicia sesión con un email y devuelve el token de DRF.

        Sin contraseña: es un atajo deliberado de pruebas. `ENFORCE_TEST_EMAIL`
        limita el daño exigiendo el patrón `test_payer_<dígitos>@testuser.com`.
        El usuario se crea con `get_or_create`, así que el mismo email siempre
        devuelve la misma sesión.
        """
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "Email requerido"}, status=400)
        if settings.ENFORCE_TEST_EMAIL and not TEST_EMAIL_RE.match(email):
            return Response(
                {
                    "detail": "Usa un email de prueba con el formato test_payer_123456@testuser.com"
                },
                status=400,
            )
        user, _ = User.objects.get_or_create(username=email, defaults={"email": email})
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "email": user.email})


class ConfigView(APIView):
    """Entrega la Public Key de MP al frontend.

    Permite configurar las credenciales de Mercado Pago en un solo lugar: el
    frontend nunca las tiene en su bundle.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"public_key": settings.MP_PUBLIC_KEY})


# ---------- Productos / carrito ----------
class ProductListView(APIView):
    """Catálogo completo, ordenado por id. Público."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            ProductSerializer(Product.objects.all().order_by("id"), many=True).data
        )


class CartView(APIView):
    """Carrito del usuario: consultar, agregar y vaciar."""

    def get(self, request):
        items = (
            CartItem.objects.filter(user=request.user)
            .select_related("product")
            .order_by("id")
        )
        total = sum((i.product.price * i.quantity for i in items), Decimal("0"))
        return Response(
            {
                "items": CartItemSerializer(items, many=True).data,
                "total": f"{total:.2f}",
            }
        )

    def post(self, request):
        """Agrega (incrementa) un producto al carrito.

        Si la línea ya existe se incrementa su cantidad en vez de duplicarla,
        lo que garantiza `CartItem.Meta.unique_together`.
        """
        product = get_object_or_404(Product, pk=request.data.get("product_id"))
        qty = max(int(request.data.get("quantity", 1)), 1)
        item, created = CartItem.objects.get_or_create(
            user=request.user, product=product, defaults={"quantity": qty}
        )
        if not created:
            item.quantity += qty
            item.save()
        return self.get(request)

    def delete(self, request):
        """Vacía el carrito completo del usuario."""
        CartItem.objects.filter(user=request.user).delete()
        return self.get(request)


class CartItemView(APIView):
    """Operaciones sobre una línea concreta del carrito."""

    def patch(self, request, product_id):
        """Fija la cantidad de una línea. Si llega `<= 0`, la línea se elimina.

        Así el botón "−" del carrito puede bajar de 1 a 0 sin que la UI tenga que
        comprobar nada: bajar de 1 borra el producto.
        """
        qty = int(request.data.get("quantity", 1))
        item = get_object_or_404(CartItem, user=request.user, product_id=product_id)
        if qty <= 0:
            item.delete()
        else:
            item.quantity = qty
            item.save()
        return CartView().get(request)

    def delete(self, request, product_id):
        """Elimina una línea del carrito."""
        CartItem.objects.filter(user=request.user, product_id=product_id).delete()
        return CartView().get(request)


# ---------- Tarjetas ----------
class CardListView(APIView):
    """Tarjetas guardadas del usuario."""

    def get(self, request):
        """Lista las tarjetas: primero la predeterminada, luego por id descendente."""
        cards = SavedCard.objects.filter(user=request.user).order_by(
            "-is_default", "-id"
        )
        return Response(SavedCardSerializer(cards, many=True).data)

    def post(self, request):
        """Guarda una tarjeta en la cuenta de MP del usuario.

        Recibe un token de un solo uso. Crea el customer si no existe y marca la
        primera tarjeta como `is_default`.
        """
        token = request.data.get("token")
        if not token:
            return Response({"detail": "Falta el token de la tarjeta"}, status=400)
        try:
            card = mp.save_card(request.user, token)
        except mp.MPError as exc:
            return mp_error_response(exc)
        return Response(SavedCardSerializer(card).data, status=201)


class CardDetailView(APIView):
    """Eliminación de una tarjeta guardada."""

    def delete(self, request, pk):
        """Borra la tarjeta en MP y en la base local.

        `pk` es el id local, no el de MP. Un 404 de MP se ignora a propósito: la
        tarjeta ya no existe en MP, así que borrarla localmente es lo correcto.
        """
        card = get_object_or_404(SavedCard, pk=pk, user=request.user)
        try:
            mp.delete_card(card)
        except mp.MPError as exc:
            return mp_error_response(exc)
        return Response(status=204)


# ---------- Órdenes ----------
class OrderListCreateView(APIView):
    """Listado y creación de órdenes."""

    def get(self, request):
        """Lista las órdenes del usuario, más recientes primero, con sus items."""
        orders = (
            Order.objects.filter(user=request.user)
            .order_by("-id")
            .prefetch_related("items__product")
        )
        return Response(OrderSerializer(orders, many=True).data)

    def post(self, request):
        """Crea la orden y la cobra contra Mercado Pago. Endpoint central del proyecto.

        Secuencia: valida el token y el carrito → recalcula el total desde la base
        → persiste `Order` + `OrderItem` en una transacción → llama a
        `POST /v1/orders` con `X-Idempotency-Key` → copia el estado devuelto.

        Los comentarios `PASO n` del cuerpo marcan los mismos puntos para quien
        quiere seguir la ejecución línea a línea.

        Detalles que importan:
        - El total se recalcula aquí; cualquier importe del cliente se ignora.
        - `saved_card_id` se busca filtrando por `user`, así que nadie puede pagar
          con la tarjeta de otro usuario.
        - Se usa `mp.create_order` (que no lanza excepción) porque un rechazo de MP
          es un resultado esperado que hay que poder mostrar, no una excepción.
        - El éxito se detecta comprobando `id` y `status` en la order, en lugar de
          fiarse del código HTTP. En un rechazo MP responde 402 con la order dentro
          de `data` y el motivo en `errors`.
        - Un pago rechazado devuelve **402**, aunque la order sí se haya creado en
          MP. Es deliberado: el frontend trata cualquier 2xx como éxito, así que un
          201 lo haría navegar a una orden rechazada sin mostrar el motivo.
        - El carrito solo se vacía si el pago no falló, para que el usuario pueda
          reintentar con el carrito intacto.
        """
        data = request.data

        # PASO 1 — Validar el token de la tarjeta. Es obligatorio: sin él no hay
        # nada que cobrar. OJO: el token NO es el número de tarjeta, es un valor
        # opaco de un solo uso que generó el SDK de MP dentro de sus iframes
        # (ver `pay()` en frontend/app/checkout/page.tsx).
        token = data.get("token")
        if not token:
            return Response({"detail": "Falta el token de la tarjeta"}, status=400)

        # `installments` viene del cliente: se valida aquí, antes de crear nada,
        # para que un valor no numérico dé un 400 y no un 500 con la orden a medias.
        try:
            installments = max(int(data.get("installments", 1)), 1)
        except (TypeError, ValueError):
            return Response({"detail": "installments inválido"}, status=400)

        # PASO 2 — Leer el carrito PERSISTIDO, no lo que manda el cliente.
        # `select_related("product")` hace una sola consulta con JOIN en vez de
        # una por producto (N+1). Si el carrito está vacío no hay nada que cobrar.
        cart = list(
            CartItem.objects.filter(user=request.user).select_related("product")
        )
        if not cart:
            return Response({"detail": "El carrito está vacío"}, status=400)

        # El total SIEMPRE se calcula en el backend: un cliente podría mandar
        # cualquier importe y el servidor lo aceptaría.
        total = sum((i.product.price * i.quantity for i in cart), Decimal("0"))

        # PASO 3 — Decidir con qué se paga. Hay dos formas de payer, y no son
        # equivalentes ante Mercado Pago:
        #   - `customer_id`: la tarjeta ya está en una cuenta de MP del usuario
        #     (tarjeta guardada). Exige crear el customer si no existe.
        #   - `email`: tarjeta nueva sin guardar. Solo identifica al pagador.
        saved_card_id = data.get("saved_card_id")
        if saved_card_id:
            # El filtro por `user` no es decorativo: sin él, un usuario podría
            # mandar el `saved_card_id` de otra persona y pagar con su tarjeta.
            card = get_object_or_404(
                SavedCard, user=request.user, card_id_mp=saved_card_id
            )
            # El `payment_method` se resuelve desde la base, no lo manda el cliente:
            # así no puede declararse una Visa cuando la tarjeta es un Amex.
            pm_id, pm_type = card.payment_method_id, card.payment_method_type
            # Crear el customer llama a MP y puede fallar (por ejemplo con un 401 de
            # credenciales): se traduce a un 502 legible en vez de un 500.
            try:
                payer = {"customer_id": mp.get_or_create_customer(request.user)}
            except mp.MPError as exc:
                return mp_error_response(exc)
        else:
            # Tarjeta nueva: el medio de pago lo detectó el frontend a partir del
            # BIN (los primeros 6 dígitos) vía el evento `binChange`.
            pm_id = data.get("payment_method_id")
            pm_type = data.get("payment_method_type") or "credit_card"
            if not pm_id:
                return Response({"detail": "Falta payment_method_id"}, status=400)
            payer = {"email": data.get("payer_email") or request.user.email}

        # PASO 4 — Persistir la orden ANTES de llamar a Mercado Pago, dentro de una
        # transacción: o se guardan `Order` + `OrderItem` los dos, o ninguno.
        # Que la orden exista aunque el cobro falle es lo que deja el intento
        # registrado en /admin para depurar.
        with transaction.atomic():
            order = Order.objects.create(user=request.user, total=total)
            # `bulk_create` inserta todas las líneas en una sola sentencia en vez
            # de una por producto.
            OrderItem.objects.bulk_create(
                [
                    OrderItem(
                        order=order,
                        product=i.product,
                        quantity=i.quantity,
                        unit_price=i.product.price,
                    )
                    for i in cart
                ]
            )

        amount = f"{total:.2f}"

        # PASO 5 — Armar el payload de `POST /v1/orders`. Es un solo pago: la lista
        # `transactions.payments` tiene siempre un elemento, con el MISMO importe
        # que `total_amount`. `installments` ya llegó validado (el checkout manda 1,
        # que significa una sola exhibición; sin valor se usa 1 por defecto).
        payload = {
            "type": "online",
            "processing_mode": "automatic",
            "external_reference": str(order.external_reference),
            "total_amount": amount,
            "payer": payer,
            "transactions": {
                "payments": [
                    {
                        "amount": amount,
                        "payment_method": {
                            "id": pm_id,
                            "type": pm_type,
                            "token": token,
                            "installments": installments,
                        },
                    }
                ]
            },
        }

        # PASO 6 — Enviar a MP. Se usa `create_order` y NO `_ok`, así que un
        # rechazo llega como valor de retorno en vez de excepción: el éxito se
        # decide por el contenido de `body`, no por el código HTTP.
        http_status, body = mp.create_order(
            payload, idempotency_key=str(order.external_reference)
        )

        # PASO 7 — Interpretar la respuesta. La order puede venir en dos formas:
        #   - aceptada: `id` y `status` al nivel superior de `body`;
        #   - rechazada (402): dentro de `body["data"]`, con el motivo en `errors`.
        # Se normaliza a `mp_data` (OJO: no reutilizar el nombre `data`, que es el
        # `request.data` de arriba). Si no hay `id` y `status` en ninguna de las dos
        # formas, la solicitud ni siquiera creó una order en MP: se considera fallo
        # y se guarda el cuerpo crudo para diagnóstico.
        mp_data = body["data"] if isinstance(body.get("data"), dict) else body

        if "id" in mp_data and "status" in mp_data:
            mp.apply_mp_order(order, mp_data)
            errs = body.get("errors") or []
            if errs and errs[0].get("details"):
                # ej. "PAY...: high_risk"
                order.status_detail = str(errs[0]["details"][0])[:200]
                order.save()

            # La order SÍ existe en MP, pero el pago fue rechazado. Importa no
            # caer aquí al 201 del final: el frontend trata cualquier 2xx como
            # éxito, navegaría a la orden y el usuario aterrizaría en una
            # pantalla rechazada sin ver el motivo (que además solo vive en el
            # `status_detail`, un código, no un mensaje).
            #
            # Por eso un pago rechazado devuelve 402: el frontend ya lo sabe
            # manejar sin tocar una línea — `api.ts` lanza con cualquier `!res.ok`
            # y `errorMessage()` concatena el `detail` con el mensaje de MP que
            # viene en `mp`. El carrito NO se vacía, así que el reintento es un
            # botón y no una reconstrucción.
            #
            # Se comprueba el estado del PAGO además del normalizado: los dos
            # niveles son cosas distintas y `display_status` solo mira el de la
            # order, así que una order `processed` con el pago `rejected` se
            # normalizaría como "approved". Mirar ambos cierra ese hueco.
            if order.payment_status == "rejected" or mp.display_status(order) == "rejected":
                return Response(
                    {
                        "detail": "Mercado Pago rechazó el pago",
                        "mp_status": http_status,
                        "mp": body,
                        "order_id": order.id,
                    },
                    status=status.HTTP_402_PAYMENT_REQUIRED,
                )
        else:
            # Camino de fallo: la orden queda en la base con el motivo del
            # rechazo, truncado a los 200 caracteres del campo del modelo.
            order.status = "failed"
            order.status_detail = json.dumps(body, ensure_ascii=False)[:200]
            order.save()
            # Se devuelve 400 con `mp_status` y `mp` para que la UI muestre el
            # motivo real: `errorMessage()` en el frontend lo extrae de `data.mp`.
            return Response(
                {
                    "detail": "Mercado Pago rechazó la solicitud",
                    "mp_status": http_status,
                    "mp": body,
                    "order_id": order.id,
                },
                status=400,
            )

        # PASO 8 — Vaciar el carrito SOLO si el pago no falló. Si el estado es
        # `pending` se vacía igual: MP ya aceptó el cobro y dejar los productos en
        # el carrito invitaría a pagarlos dos veces. Ojo con el costo: un pendiente
        # puede terminar rechazado más tarde, y entonces el usuario tendría que
        # volver a armar su carrito.
        if mp.display_status(order) in {"approved", "pending"}:
            CartItem.objects.filter(user=request.user).delete()

        return Response(OrderSerializer(order).data, status=201)


class OrderDetailView(APIView):
    """Detalle de una orden, solo del usuario autenticado."""

    def get(self, request, pk):
        """Devuelve la orden, re-consultando a MP si su estado aún puede cambiar.

        Eso convierte un GET barato en una llamada externa, pero es lo que permite
        que el polling del frontend reciba el estado más fresco. Si la consulta
        falla se devuelve el último estado conocido en lugar de un error.

        La decisión de re-consultar la toma `mp.needs_refresh`, no
        `FINAL_ORDER_STATUSES` directamente: una order puede estar `processed` —un
        estado final de la order— y aun así tener el pago `pending`. En ese caso sí
        hay que volver a preguntar, o el polling del frontend serviría un valor
        congelado indefinidamente.
        """
        order = get_object_or_404(Order, pk=pk, user=request.user)
        if mp.needs_refresh(order):
            try:
                mp.refresh_order(order)
            except mp.MPError:
                pass  # devolvemos lo último que tenemos
        return Response(OrderSerializer(order).data)


# ---------- Webhook ----------
class WebhookView(APIView):
    """Notificación de MP cuando cambia el estado de una orden.

    No confía en el payload: el `data.id` solo sirve para localizar la orden y el
    estado se obtiene siempre re-consultando a la API de MP.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        """Procesa la notificación.

        Códigos de respuesta, con su intención:
        - `200` notificación vacía, de otro tipo, o de una orden que no es nuestra
          (acusarla evita reintentos inofensivos de MP).
        - `401` firma inválida.
        - `500` no se pudo consultar a MP; se responde 500 a propósito para que MP
          reintente la notificación.
        """
        data_id = (request.data.get("data") or {}).get(
            "id"
        ) or request.query_params.get("data.id")
        if not data_id:
            return Response(status=200)
        if not mp.valid_webhook_signature(request, data_id):
            return Response({"detail": "Firma inválida"}, status=401)
        order = Order.objects.filter(mp_order_id=data_id).first()
        if order:
            try:
                mp.refresh_order(order)  # consultamos a MP, no confiamos en el payload
            except mp.MPError:
                return Response(status=500)  # MP reintentará
        return Response(status=200)
