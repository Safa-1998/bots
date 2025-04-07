import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import logging
import aiohttp
import json
import sys
from dotenv import load_dotenv
import os

load_dotenv("data.env")

API_TOKEN = os.getenv("API_TOKEN")
CHECK_BONUS_BOT_URL = os.getenv("CHECK_BONUS_BOT_URL")
MS_TOKEN = os.getenv("MS_TOKEN")
SKLAD_NAME = os.getenv("SKLAD_NAME")
TARGET_USER_ID = int(os.getenv("TARGET_USER_ID"))


def load_product_codes():
    with open("products.json", encoding="utf-8") as f:
        return json.load(f)

PRODUCT_CODES = load_product_codes()
CATEGORIES = list(PRODUCT_CODES.keys())
USER_CARTS = {}
PRODUCT_CACHE = {}

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],
    format="%(asctime)s [%(levelname)s] %(message)s"
)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

async def get_products_from_api(category):
    if category in PRODUCT_CACHE:
        return PRODUCT_CACHE[category]

    url = "https://api.moysklad.ru/api/remap/1.2/entity/assortment"
    headers = {
        "Authorization": f"Bearer {MS_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    result = []
    codes = PRODUCT_CODES.get(category, {})
    async with aiohttp.ClientSession() as session:
        for code, name in codes.items():
            async with session.get(f"{url}?filter=externalCode={code}", headers=headers) as resp:
                if resp.status != 200:
                    continue
                data = await resp.json()
                rows = data.get("rows", [])
                if not rows:
                    continue
                item = rows[0]
                stock = item.get("stock", 0)
                if stock <= 0:
                    continue
                price = 0
                sale_prices = item.get("salePrices")
                if sale_prices:
                    price = int(sale_prices[0].get("value", 0)) // 100
                result.append({"name": name, "price": price, "quantity": int(stock), "code": code})
    PRODUCT_CACHE[category] = result
    return result

async def get_product_by_code(code):
    for category in CATEGORIES:
        items = await get_products_from_api(category)
        for item in items:
            if item["code"] == code:
                return item
    return None

def product_keyboard(code):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Добавить в корзину", callback_data=f"add_{code}")]
    ])

@dp.message(F.text == "/start")
async def start_menu(message: Message):
    contact_button = KeyboardButton(text="📱 Отправить номер", request_contact=True)
    buttons = [
        [contact_button],
        [KeyboardButton(text="Диваны"), KeyboardButton(text="Кресла")],
        [KeyboardButton(text="Столы"), KeyboardButton(text="Шкафы")],
        [KeyboardButton(text="🛍 Корзина"), KeyboardButton(text="🎯 Проверить баллы")],
        [KeyboardButton(text="🔍 Поиск по названию")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Выберите категорию мебели или отправьте номер для оформления запроса:", reply_markup=keyboard)

@dp.message(F.contact)
async def handle_contact(message: Message):
    phone = message.contact.phone_number
    user_id = str(message.from_user.id)
    USER_CARTS[user_id + "_phone"] = phone
    await message.answer("📱 Номер получен. Теперь вы можете оформить заказ через корзину.")

@dp.message(F.text.in_(CATEGORIES))
async def show_products_by_category(message: Message):
    category = message.text
    items = await get_products_from_api(category)
    if not items:
        await message.answer(f"Нет товаров в категории '{category}' в наличии.")
        return
    for item in items:
        await message.answer(
            text=f"{item['name']}\nЦена: {item['price']}₽\nДоступно: {item['quantity']} шт.",
            reply_markup=product_keyboard(item['code'])
        )

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    code = callback.data.split("_")[1]
    USER_CARTS.setdefault(user_id, []).append(code)
    await callback.answer("Добавлено в корзину!")

@dp.message(F.text == "🛍 Корзина")
async def show_cart(message: Message):
    user_id = str(message.from_user.id)
    cart = USER_CARTS.get(user_id, [])
    if not cart:
        await message.answer("♻️ Корзина обновлена.")
        return

    summary = {}
    for code in cart:
        summary[code] = summary.get(code, 0) + 1

    total = 0
    text = "<b>🛍 Ваша корзина:</b>\n"
    keyboard = []

    for code, qty in summary.items():
        item = await get_product_by_code(code)
        if item:
            name = item["name"]
            price = item["price"]
            total += price * qty
            text += f"{name} — {price}₽ × {qty} = {price * qty}₽\n"
            keyboard.append([
                InlineKeyboardButton(text=f"➖ {name}", callback_data=f"decrease_{code}"),
                InlineKeyboardButton(text=f"{qty} шт.", callback_data="noop"),
                InlineKeyboardButton(text="➕", callback_data=f"increase_{code}")
            ])

    text += f"\n<b>💰 Итого: {total}₽</b>"
    keyboard.append([InlineKeyboardButton(text="📩 Отправить запрос", callback_data="send_request")])
    keyboard.append([InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")])
    await message.answer(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


@dp.callback_query(F.data.startswith("increase_"))
async def increase_quantity(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    code = callback.data.split("_")[1]
    USER_CARTS.setdefault(user_id, []).append(code)
    await callback.answer("📦 Количество увеличено")
    await show_cart(callback.message)


@dp.callback_query(F.data.startswith("decrease_"))
async def decrease_quantity(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    code = callback.data.split("_")[1]
    cart = USER_CARTS.get(user_id, [])
    if code in cart:
        cart.remove(code)
    await callback.answer("📦 Количество уменьшено")
    await show_cart(callback.message)


@dp.callback_query(F.data == "send_request")
async def send_request(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    phone = USER_CARTS.get(user_id + "_phone")

    if not phone:
        contact_button = KeyboardButton(text="📱 Отправить номер", request_contact=True)
        keyboard = ReplyKeyboardMarkup(keyboard=[[contact_button]], resize_keyboard=True, one_time_keyboard=True)
        await callback.message.answer("📱 Пожалуйста, отправьте свой номер телефона перед оформлением запроса:", reply_markup=keyboard)
        await callback.answer()
        return

    cart = USER_CARTS.get(user_id, [])
    if not cart:
        await callback.answer("Корзина пуста", show_alert=True)
        return

    summary = {}
    for code in cart:
        summary[code] = summary.get(code, 0) + 1

    text = f"<b>📥 Новый запрос</b>\n"
    text += f"<b>📱 Номер телефона:</b> {phone}\n"
    text += "<b>🛍 Корзина:</b>\n"

    total = 0
    for code, qty in summary.items():
        item = await get_product_by_code(code)
        if item:
            name = item['name']
            price = item['price']
            total += price * qty
            text += f"{name} — {price}₽ × {qty} = {price * qty}₽\n"

    text += f"\n<b>💰 Итого: {total}₽</b>"
    try:
        await bot.send_message(chat_id=TARGET_USER_ID, text=text)
        await callback.message.answer("✅ Ваш запрос отправлен. Ожидайте ответа.")
        USER_CARTS[user_id] = []
    except Exception as e:
        logging.error(f"Ошибка при отправке запроса: {e}")
        await callback.answer("❗ Не удалось отправить запрос.", show_alert=True)

@dp.callback_query(F.data.startswith("remove_"))
async def remove_item(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    code = callback.data.split("_")[1]
    cart = USER_CARTS.get(user_id, [])
    if code in cart:
        cart.remove(code)
    await callback.answer("Удалено из корзины.")
    await show_cart(callback.message)

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    USER_CARTS[user_id] = []
    await callback.message.edit_text("🧺 Корзина очищена.")

@dp.message(F.text == "🔍 Поиск по названию")
async def prompt_search(message: Message):
    await message.answer("Введите часть названия товара для поиска:")

@dp.message(F.text == "🎯 Проверить баллы")
async def check_bonus(message: Message):
    await message.answer(
        "Перейдите к боту, чтобы проверить баллы:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Перейти к боту с баллами", url=CHECK_BONUS_BOT_URL)]
        ])
    )

@dp.message()
async def handle_search_query(message: Message):
    query = message.text.lower()
    results = []
    for category in CATEGORIES:
        items = await get_products_from_api(category)
        matches = [item for item in items if query in item['name'].lower()]
        results.extend(matches)
    if not results:
        await message.answer("Товар не найден.")
        return
    for item in results:
        await message.answer(
            text=f"{item['name']}\nЦена: {item['price']}₽\nДоступно: {item['quantity']} шт.",
            reply_markup=product_keyboard(item['code'])
        )

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
