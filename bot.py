import os
import requests
from io import BytesIO

import telebot
from telebot import types
from math import radians, sin, cos, sqrt, atan2

from config import (
    BOT_TOKEN, ADMIN_ID, CURRENCY,
    WAREHOUSE_LAT, WAREHOUSE_LON,
    MANAGER_PHONE, MANAGER_PHONE_PRETTY,
)
from data import MATERIALS, TONNAGE, DELIVERY_ZONES, OUT_OF_ZONE

bot = telebot.TeleBot(BOT_TOKEN)

orders = {}


def get_order(chat_id: int) -> dict:
    if chat_id not in orders:
        orders[chat_id] = {
            "material": None,
            "tons": None,
            "is_full_body": False,
            "distance_km": None,
            "delivery": None,
            "name": None,
            "phone": None,
            "location": None,
        }
    return orders[chat_id]


def reset_order(chat_id: int):
    orders[chat_id] = {
        "material": None,
        "tons": None,
        "is_full_body": False,
        "distance_km": None,
        "delivery": None,
        "name": None,
        "phone": None,
        "location": None,
    }


def haversine(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def get_delivery_cost(distance_km: float):
    for max_km, price in DELIVERY_ZONES:
        if distance_km <= max_km:
            return price
    return OUT_OF_ZONE


def calc_price(material_key: str, tons, delivery: int) -> dict:
    mat = MATERIALS[material_key]

    if mat.get("full_body_only"):
        cargo = mat["full_body_price"]
        return {
            "price_per_ton": None,
            "cargo": cargo,
            "delivery": delivery,
            "total": cargo + delivery,
            "is_full_body": True,
        }

    price_per_ton = mat["price_per_ton"]
    cargo = price_per_ton * tons
    return {
        "price_per_ton": price_per_ton,
        "cargo": cargo,
        "delivery": delivery,
        "total": cargo + delivery,
        "is_full_body": False,
    }


def phone_html() -> str:
    """Кликабельный телефон для вставки в текст."""
    return f'<a href="tel:+{MANAGER_PHONE.lstrip("8")}">{MANAGER_PHONE_PRETTY}</a>'


def send_material_photo(chat_id: int, photo_source: str, caption: str) -> bool:
    """
    Универсальная отправка фото.
    • Если photo_source начинается с http:// или https:// — скачивает и отправляет.
    • Иначе — открывает как локальный файл.
    Возвращает True при успехе, False при ошибке.
    """
    try:
        # Вариант 1: ссылка
        if photo_source.startswith(("http://", "https://")):
            resp = requests.get(photo_source, timeout=15)
            resp.raise_for_status()
            bot.send_photo(
                chat_id, BytesIO(resp.content),
                caption=caption, parse_mode="HTML"
            )
            return True

        # Вариант 2: локальный файл
        if not os.path.exists(photo_source):
            print(f"Файл не найден: {photo_source}")
            return False

        with open(photo_source, "rb") as photo:
            bot.send_photo(
                chat_id, photo,
                caption=caption, parse_mode="HTML"
            )
        return True

    except Exception as e:
        print(f"Не удалось отправить фото: {e}")
        return False


# ---------- /start ----------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    reset_order(chat_id)

    kb = types.InlineKeyboardMarkup(row_width=2)
    for key, mat in MATERIALS.items():
        kb.add(types.InlineKeyboardButton(mat["name"], callback_data=f"mat:{key}"))

    text = (
        "🚛 Привет! На связи доставка сыпучих грузов до 6 тонн.\n\n"
        "Никаких «позвоните, уточним» — всё считаем прямо здесь.\n\n"
        "📦 <b>Наш арсенал:</b>\n"
        "• ОПГС и ПГС — универсальные смеси ⛰\n"
        "• Песок — для стройки и песочницы 🏖\n"
        "• Обогащённый песок — чистота и качество ✨\n"
        "• Чернозём — сад и огород 🌱\n"
        "• Перегной и навоз — урожай на зависть соседям 🍅\n\n"
        f"📞 Связаться напрямую: {phone_html()}\n\n"
        "Что заказываем?"
    )

    bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")


# ---------- /contact ----------
@bot.message_handler(commands=["contact"])
def cmd_contact(message):
    bot.send_message(
        message.chat.id,
        f"📞 <b>Связь с менеджером</b>\n\n"
        f"Телефон: {phone_html()}\n"
        f"Работаем ежедневно с 9:00 до 20:00.",
        parse_mode="HTML",
    )


# ---------- Выбор материала ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("mat:"))
def choose_material(call):
    chat_id = call.message.chat.id
    material_key = call.data.split(":")[1]

    if material_key not in MATERIALS:
        bot.answer_callback_query(call.id, "Материал не найден")
        return

    order = get_order(chat_id)
    order["material"] = material_key
    order["tons"] = None
    order["is_full_body"] = False
    order["distance_km"] = None
    order["delivery"] = None

    mat = MATERIALS[material_key]

    # ------- Перегной: только полный кузов с горкой -------
    if mat.get("full_body_only"):
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "🚛 Полный кузов с горкой",
            callback_data=f"fullbody:{material_key}"
        ))
        bot.edit_message_text(
            f"Вы выбрали: <b>{mat['name']}</b>\n\n"
            f"Для этого материала доступен только "
            f"<b>полный кузов с горкой</b>.\n\n"
            f"💰 Цена: <b>{mat['full_body_price']} {CURRENCY}</b> + доставка\n\n"
            f"Нажмите, чтобы посмотреть, как это выглядит 👇",
            chat_id, call.message.message_id,
            reply_markup=kb, parse_mode="HTML",
        )
        bot.answer_callback_query(call.id)
        return

    # ------- Обычный материал: выбор тоннажа -------
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(*[types.InlineKeyboardButton(f"{t} т", callback_data=f"tons:{t}") for t in TONNAGE])

    bot.edit_message_text(
        f"Вы выбрали: <b>{mat['name']}</b>\n"
        f"Цена: {mat['price_per_ton']} {CURRENCY}/т\n\n"
        f"Сколько тонн нужно?",
        chat_id, call.message.message_id, reply_markup=kb, parse_mode="HTML",
    )
    bot.answer_callback_query(call.id)


# ---------- Полный кузов с горкой (Перегной) ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("fullbody:"))
def choose_full_body(call):
    chat_id = call.message.chat.id
    material_key = call.data.split(":")[1]
    mat = MATERIALS.get(material_key)

    if not mat or not mat.get("full_body_only"):
        bot.answer_callback_query(call.id, "Ошибка выбора")
        return

    order = get_order(chat_id)
    order["material"] = material_key
    order["tons"] = None
    order["is_full_body"] = True

    caption = (
        f"📸 Так выглядит <b>полный кузов с горкой</b>.\n\n"
        f"📦 Материал: <b>{mat['name']}</b>\n"
        f"💰 Цена: <b>{mat['full_body_price']} {CURRENCY}</b>\n\n"
        f"📍 Далее укажите адрес доставки 👇"
    )

    # Универсальная отправка фото (файл или ссылка)
    photo_sent = send_material_photo(chat_id, mat["full_body_photo"], caption)

    # Если фото не ушло — показываем текст
    if not photo_sent:
        bot.send_message(
            chat_id,
            f"📸 Фото временно недоступно.\n\n"
            f"📦 {mat['name']} — полный кузов с горкой\n"
            f"💰 Цена: {mat['full_body_price']} {CURRENCY}\n\n"
            f"📍 Далее укажите адрес доставки 👇",
            parse_mode="HTML",
        )

    # Кнопка геолокации
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📍 Отправить геолокацию", request_location=True))

    bot.send_message(chat_id, "📍 Отправьте вашу геолокацию:", reply_markup=kb)
    bot.answer_callback_query(call.id)


# ---------- Выбор тоннажа ----------
@bot.callback_query_handler(func=lambda c: c.data.startswith("tons:"))
def choose_tons(call):
    chat_id = call.message.chat.id
    tons = int(call.data.split(":")[1])
    order = get_order(chat_id)

    if not order.get("material"):
        bot.answer_callback_query(call.id, "Сначала выберите материал", show_alert=True)
        return

    if MATERIALS[order["material"]].get("full_body_only"):
        bot.answer_callback_query(call.id, "Для этого материала тоннаж не выбирается",
                                  show_alert=True)
        return

    order["tons"] = tons

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📍 Отправить геолокацию", request_location=True))

    bot.send_message(
        chat_id,
        f"✅ Материал: <b>{MATERIALS[order['material']]['name']}</b>\n"
        f"⚖️ Объём: <b>{tons} т</b>\n\n"
        f"📍 Отправьте вашу геолокацию:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    bot.answer_callback_query(call.id)


# ---------- Геолокация ----------
@bot.message_handler(content_types=["location"])
def handle_location(message):
    chat_id = message.chat.id
    order = get_order(chat_id)

    if not order.get("material") or (not order.get("tons") and not order.get("is_full_body")):
        bot.send_message(chat_id, "Сначала выберите материал. Нажмите /start")
        return

    lat, lon = message.location.latitude, message.location.longitude
    distance = haversine(WAREHOUSE_LAT, WAREHOUSE_LON, lat, lon) * 1.3
    delivery = get_delivery_cost(distance)

    if delivery is None:
        bot.send_message(
            chat_id,
            "😔 К сожалению, ваш адрес вне зоны обслуживания.\n\n"
            f"Свяжитесь с менеджером для индивидуального расчёта: "
            f"{phone_html()}",
            parse_mode="HTML",
        )
        return

    order["distance_km"] = round(distance, 1)
    order["delivery"] = delivery
    order["location"] = (lat, lon)

    msg = bot.send_message(
        chat_id,
        "📍 Адрес принят.\n\n"
        "Как к вам обращаться? Введите ваше <b>имя</b>:",
        reply_markup=types.ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, ask_phone)


# ---------- Имя -> телефон ----------
def ask_phone(message):
    chat_id = message.chat.id
    order = get_order(chat_id)

    if not message.text or len(message.text.strip()) < 2:
        msg = bot.send_message(chat_id, "Пожалуйста, введите корректное имя (минимум 2 символа):")
        bot.register_next_step_handler(msg, ask_phone)
        return

    order["name"] = message.text.strip()

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📱 Отправить телефон", request_contact=True))

    msg = bot.send_message(
        chat_id,
        f"Приятно познакомиться, <b>{order['name']}</b>! 👋\n\n"
        f"Отправьте номер телефона кнопкой ниже или введите вручную "
        f"(например, <code>+7 999 123-45-67</code>):",
        reply_markup=kb,
        parse_mode="HTML",
    )
    bot.register_next_step_handler(msg, ask_confirm)


# ---------- Телефон -> итоговый чек ----------
def ask_confirm(message):
    chat_id = message.chat.id
    order = get_order(chat_id)

    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = (message.text or "").strip()

    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 10:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.add(types.KeyboardButton("📱 Отправить телефон", request_contact=True))
        msg = bot.send_message(
            chat_id,
            "Похоже, номер введён неверно. Попробуйте ещё раз "
            "или нажмите кнопку ниже:",
            reply_markup=kb,
        )
        bot.register_next_step_handler(msg, ask_confirm)
        return

    order["phone"] = phone

    mat = MATERIALS[order["material"]]
    calc = calc_price(order["material"], order["tons"], order["delivery"])

    if calc["is_full_body"]:
        body_line = "🚛 Объём: <b>Полный кузов с горкой</b>"
        cargo_line = f"💰 Товар: <b>{calc['cargo']} {CURRENCY}</b>"
    else:
        body_line = f"⚖️ Объём: <b>{order['tons']} т</b>"
        cargo_line = (
            f"💰 Товар: {calc['price_per_ton']} × {order['tons']} = "
            f"<b>{calc['cargo']} {CURRENCY}</b>"
        )

    text = (
        f"📋 <b>Проверьте заявку:</b>\n\n"
        f"📦 Материал: <b>{mat['name']}</b>\n"
        f"{body_line}\n\n"
        f"{cargo_line}\n"
        f"🚚 Доставка: <b>{calc['delivery']} {CURRENCY}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Итого: {calc['total']} {CURRENCY}</b>\n\n"
        f"👤 Имя: <b>{order['name']}</b>\n"
        f"📱 Телефон: <b>{order['phone']}</b>\n\n"
        f"Отправить заявку менеджеру?"
    )

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Отправить", callback_data="confirm"),
        types.InlineKeyboardButton("🔄 Заново", callback_data="restart"),
    )

    bot.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")


# ---------- Подтверждение ----------
@bot.callback_query_handler(func=lambda c: c.data == "confirm")
def confirm_order(call):
    chat_id = call.message.chat.id
    order = get_order(chat_id)

    if (not order.get("material")
        or not order.get("delivery")
        or not order.get("name")
        or not order.get("phone")
        or (not order.get("tons") and not order.get("is_full_body"))):
        bot.answer_callback_query(call.id, "Данные не заполнены. Начните заново /start",
                                  show_alert=True)
        return

    mat = MATERIALS[order["material"]]
    calc = calc_price(order["material"], order["tons"], order["delivery"])
    user = call.from_user
    username = f"@{user.username}" if user.username else f"id{user.id}"

    if calc["is_full_body"]:
        body_str = "Полный кузов с горкой"
    else:
        body_str = f"{order['tons']} т"

    bot.send_message(
        chat_id,
        f"🎉 <b>Заявка отправлена!</b>\n\n"
        f"📦 {mat['name']} — <b>{body_str}</b>\n"
        f"💰 Итого: <b>{calc['total']} {CURRENCY}</b>\n\n"
        f"📞 Менеджер свяжется с вами по номеру "
        f"<b>{order['phone']}</b> в ближайшее время.\n\n"
        f"Если нужно срочно — звоните: {phone_html()}",
        parse_mode="HTML",
    )

    admin_text = (
        f"🔔 <b>НОВАЯ ЗАЯВКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{order['name']}</b>\n"
        f"📱 Телефон: <b>{order['phone']}</b>\n"
        f"💬 Telegram: {username}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 Материал: <b>{mat['name']}</b>\n"
        f"⚖️ Объём: <b>{body_str}</b>\n"
        f"📍 Расстояние: {order['distance_km']} км\n"
        f"🚚 Доставка: {order['delivery']} {CURRENCY}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>ИТОГО: {calc['total']} {CURRENCY}</b>"
    )
    try:
        bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")

        if order.get("location"):
            lat, lon = order["location"]
            bot.send_location(ADMIN_ID, lat, lon)
    except Exception as e:
        print(f"Не удалось уведомить админа: {e}")

    reset_order(chat_id)
    bot.answer_callback_query(call.id, "Заявка отправлена ✅")


# ---------- Заново ----------
@bot.callback_query_handler(func=lambda c: c.data == "restart")
def restart(call):
    chat_id = call.message.chat.id
    reset_order(chat_id)

    kb = types.InlineKeyboardMarkup(row_width=2)
    for key, mat in MATERIALS.items():
        kb.add(types.InlineKeyboardButton(mat["name"], callback_data=f"mat:{key}"))

    bot.edit_message_text(
        "Что заказываем?", chat_id, call.message.message_id, reply_markup=kb
    )
    bot.answer_callback_query(call.id)


# ---------- Фоллбек ----------
@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.send_message(message.chat.id, "Нажмите /start, чтобы начать заказ заново 🚛")


# ---------- Запуск ----------
if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling()