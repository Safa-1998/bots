import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, LabeledPrice
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import logging
import aiohttp
import json
import sys
import os

API_TOKEN = ''
CHECK_BONUS_BOT_URL = ''
MS_TOKEN = ''
SKLAD_NAME = ''
PROVIDER_TOKEN = ''

# Загрузка внешних кодов из JSON-файла по категориям
def load_product_codes():
    with open("products.json", encoding="utf-8") as f:
        return json.load(f)

PRODUCT_CODES = load_product_codes()
CATEGORIES = list(PRODUCT_CODES.keys())
USER_CARTS = {}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("log.txt", encoding="utf-8")
    ],
    format="%(asctime)s [%(levelname)s] %(message)s"
)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

async def get_products_from_api(category):
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
                    logging.error(f"Ошибка при получении данных по коду {code}: {resp.status}")
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
    return result

def back_to_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Вернуться к категориям", callback_data="back_to_main")]
    ])

def product_keyboard(code):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Добавить в корзину", callback_data=f"add_{code}")],
        [InlineKeyboardButton(text="⬅ Вернуться к категориям", callback_data="back_to_main")]
    ])

@dp.message(F.text == "/start")
async def start_menu(message: Message):
    buttons = [
        [KeyboardButton(text="Диваны"), KeyboardButton(text="Кресла")],
        [KeyboardButton(text="Столы"), KeyboardButton(text="Шкафы")],
        [KeyboardButton(text="🛍 Корзина"), KeyboardButton(text="🎯 Проверить баллы")],
        [KeyboardButton(text="🔍 Поиск по названию")]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    await message.answer("Выберите категорию мебели:", reply_markup=keyboard)

@dp.message(F.text.in_(CATEGORIES))
async def show_products_by_category(message: Message):
    category = message.text
    items = await get_products_from_api(category)
    if not items:
        await message.answer(f"Нет товаров в категории '{category}' в наличии на складе.", reply_markup=back_to_main_keyboard())
        return
    for item in items:
        await message.answer(
            text=f"{item['name']}\nЦена: {item['price']}₽\nДоступно к покупке: {item['quantity']} шт.",
            reply_markup=product_keyboard(item['code'])
        )

@dp.callback_query(F.data.startswith("add_"))
async def add_to_cart(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    code = callback.data.split("_")[1]
    for category, items in PRODUCT_CODES.items():
        if code in items:
            name = items[code]
            break
    else:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    USER_CARTS.setdefault(user_id, []).append(code)
    await callback.answer("Добавлено в корзину!")

@dp.message(F.text == "🛍 Корзина")
async def show_cart(message: Message):
    user_id = str(message.from_user.id)
    cart = USER_CARTS.get(user_id, [])
    if not cart:
        await message.answer("🧺 Ваша корзина пуста.", reply_markup=back_to_main_keyboard())
        return

    product_map = {code: name for cat in PRODUCT_CODES.values() for code, name in cat.items()}
    summary = {}
    for code in cart:
        summary[code] = summary.get(code, 0) + 1

    total = 0
    text = "<b>🛍 Ваша корзина:</b>\n"
    keyboard = []
    for code, qty in summary.items():
        for cat in CATEGORIES:
            if code in PRODUCT_CODES[cat]:
                items = await get_products_from_api(cat)
                item = next((x for x in items if x['code'] == code), None)
                if item:
                    price = item['price']
                    name = item['name']
                    total += price * qty
                    text += f"{name} — {price}₽ × {qty} = {price * qty}₽\n"
                    keyboard.append([InlineKeyboardButton(text=f"❌ Удалить {name}", callback_data=f"remove_{code}")])
                break

    text += f"\n<b>Итого: {total}₽</b>"
    keyboard.append([InlineKeyboardButton(text="💳 Перейти к оплате", callback_data="pay_inline")])
    keyboard.append([InlineKeyboardButton(text="🗑 Очистить корзину", callback_data="clear_cart")])
    keyboard.append([InlineKeyboardButton(text="⬅ Вернуться к категориям", callback_data="back_to_main")])

    await message.answer(text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

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
    await callback.message.edit_text("🧺 Корзина очищена.", reply_markup=back_to_main_keyboard())

@dp.callback_query(F.data == "pay_inline")
async def inline_payment(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    cart = USER_CARTS.get(user_id, [])
    if not cart:
        await callback.answer("Корзина пуста", show_alert=True)
        return

    summary = {}
    for code in cart:
        summary[code] = summary.get(code, 0) + 1

    prices = []
    total = 0
    for code, qty in summary.items():
        for cat in CATEGORIES:
            if code in PRODUCT_CODES[cat]:
                items = await get_products_from_api(cat)
                item = next((x for x in items if x['code'] == code), None)
                if item:
                    name = item['name']
                    price = item['price']
                    total += price * qty
                    prices.append(LabeledPrice(label=name, amount=price * 100 * qty))
                break

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Оплата заказа",
        description="Оплатите корзину через Telegram",
        payload="furniture_payment",
        provider_token=PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        start_parameter="furniture-pay"
    )

@dp.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    user_id = str(message.from_user.id)
    USER_CARTS[user_id] = []
    await message.answer("✅ Оплата прошла успешно! Спасибо за заказ.", reply_markup=back_to_main_keyboard())

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
        await message.answer("Товар не найден.", reply_markup=back_to_main_keyboard())
        return
    for item in results:
        await message.answer(
            text=f"{item['name']}\nЦена: {item['price']}₽\nДоступно к покупке: {item['quantity']} шт.",
            reply_markup=product_keyboard(item['code'])
        )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    await start_menu(callback.message)

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
