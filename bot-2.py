"""
Медицинский навигатор — Telegram бот
Стек: Python 3.10+, aiogram 3.x
Установка: pip install aiogram
Запуск: python bot.py
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import os
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.filters import CommandStart

# ─────────────────────────────────────────
# НАСТРОЙКИ — заполни перед запуском
# ─────────────────────────────────────────
BOT_TOKEN = "ВАШ_ТОКЕН_ОТ_BOTFATHER"   # токен бота
DOCTOR_CHAT_ID = 123456789              # твой Telegram ID (узнать: @userinfobot)
CARD_NUMBER = "2200 0000 0000 0000"     # номер карты для оплаты
CARD_NAME = "Иванова Анна Ивановна"    # имя на карте

# Цены (руб)
PRICES = {
    "psychiatry":      1200,
    "therapy":         1200,
    "checkup_general": 500,
    "checkup_thyroid": 500,
    "checkup_fatigue": 500,
    "checkup_gut":     500,
    "checkup_mental":  500,
}
URGENT_SURCHARGE = 800

# ─────────────────────────────────────────
# СОСТОЯНИЯ (FSM)
# ─────────────────────────────────────────
class PsychForm(StatesGroup):
    age_sex       = State()
    height_weight = State()
    complaints    = State()
    duration      = State()
    prev_doctors  = State()
    medications   = State()
    # ПАВ-блок
    pav_select    = State()   # выбор веществ кнопками
    pav_nicotine  = State()   # уточнение: никотин
    pav_alcohol   = State()   # уточнение: алкоголь
    pav_drugs     = State()   # уточнение: наркотики
    pav_duration  = State()   # как долго употребляет
    # Финал
    answer_format = State()
    urgency       = State()

class TherapyForm(StatesGroup):
    age_sex       = State()
    height_weight = State()
    complaints    = State()
    duration      = State()
    prev_doctors  = State()
    medications   = State()
    answer_format = State()
    urgency       = State()

# ─────────────────────────────────────────
# КЛАВИАТУРЫ
# ─────────────────────────────────────────
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧠 Разбор жалоб — психиатрия/наркология", callback_data="start_psych")],
        [InlineKeyboardButton(text="🩺 Разбор жалоб — терапия",               callback_data="start_therapy")],
        [InlineKeyboardButton(text="📋 Купить готовый чекап",                  callback_data="checkups")],
        [InlineKeyboardButton(text="ℹ️ Как это работает",                      callback_data="how_it_works")],
        [InlineKeyboardButton(text="💰 Цены",                                  callback_data="prices")],
    ])

def checkup_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👩 Общий чекап (женщины 20–35)",   callback_data="buy_checkup_general")],
        [InlineKeyboardButton(text="🦋 Чекап щитовидки",               callback_data="buy_checkup_thyroid")],
        [InlineKeyboardButton(text="😴 Чекап при усталости",            callback_data="buy_checkup_fatigue")],
        [InlineKeyboardButton(text="🍽️ Чекап ЖКТ",                    callback_data="buy_checkup_gut")],
        [InlineKeyboardButton(text="🧩 Чекап психического здоровья",   callback_data="buy_checkup_mental")],
        [InlineKeyboardButton(text="← Назад",                          callback_data="back_main")],
    ])

def format_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Текстом",    callback_data="fmt_text")],
        [InlineKeyboardButton(text="🎙 Голосовым",  callback_data="fmt_voice")],
    ])

def urgency_kb(base_price: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏰ Стандарт (24 часа) — {base_price} руб",
            callback_data="urg_standard")],
        [InlineKeyboardButton(
            text=f"🔥 Срочно (2–3 часа) — {base_price + URGENT_SURCHARGE} руб",
            callback_data="urg_urgent")],
    ])

def back_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← В главное меню", callback_data="back_main")],
    ])

def pav_select_kb(selected: list):
    """Клавиатура выбора ПАВ с отметками выбранных"""
    marks = {s: "✓ " for s in selected}
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"{marks.get('никотин', '')}🚬 Никотин",   callback_data="pav_nicotine"),
            InlineKeyboardButton(text=f"{marks.get('алкоголь', '')}🍷 Алкоголь", callback_data="pav_alcohol"),
        ],
        [InlineKeyboardButton(text=f"{marks.get('наркотики', '')}💊 Наркотики",  callback_data="pav_drugs")],
        [InlineKeyboardButton(text="✅ Готово (выбрал всё)",                     callback_data="pav_done")],
        [InlineKeyboardButton(text="🚫 Не употребляю",                           callback_data="pav_none")],
    ])

def skip_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

# ─────────────────────────────────────────
# ТЕКСТЫ
# ─────────────────────────────────────────
WELCOME = (
    "👋 Привет! Я бот медицинского навигатора.\n\n"
    "Здесь ты можешь получить персональный маршрут:\n"
    "— что сдать и обследовать\n"
    "— к какому специалисту идти первым\n"
    "— на что обратить внимание на приёме\n\n"
    "Это <b>не врачебный приём и не постановка диагноза</b> — это навигация по системе здравоохранения.\n\n"
    "⚠️ Острые состояния и кризисы — не сюда. Звони 112 или на горячую линию психологической помощи "
    "8-800-2000-122 (бесплатно).\n\n"
    "Выбери что тебя интересует:"
)

HOW_IT_WORKS = (
    "ℹ️ <b>Как это работает</b>\n\n"
    "1. Выбираешь направление — психиатрия или терапия\n"
    "2. Заполняешь анкету (6–7 вопросов)\n"
    "3. Выбираешь формат ответа — текст или голос\n"
    "4. Оплачиваешь переводом на карту\n"
    "5. Присылаешь скриншот оплаты\n"
    "6. Получаешь персональный маршрут в течение 24 часов\n\n"
    "<b>Что ты получишь:</b>\n"
    "• Какие анализы и обследования сдать\n"
    "• К какому специалисту идти первым\n"
    "• На что обратить внимание на приёме\n"
    "• Красные флаги — когда нужна срочная помощь\n\n"
    "<b>Важно:</b> это медицинское просвещение, не приём врача. "
    "Финальное решение всегда за специалистом на очной консультации."
)

PRICES_TEXT = (
    "💰 <b>Цены</b>\n\n"
    "<b>Разбор жалоб:</b>\n"
    "🧠 Психиатрия/наркология — 1200 руб (24 часа)\n"
    "🩺 Терапия — 1200 руб (24 часа)\n"
    "🔥 Срочно (2–3 часа) — +800 руб\n\n"
    "<b>Готовые чекапы (PDF):</b>\n"
    "👩 Общий чекап женщины — 500 руб\n"
    "🦋 Щитовидка — 500 руб\n"
    "😴 Усталость — 500 руб\n"
    "🍽️ ЖКТ — 500 руб\n"
    "🧩 Психическое здоровье — 500 руб\n\n"
    "Оплата — переводом на карту."
)

CHECKUP_DESCRIPTIONS = {
    "checkup_general": {
        "title": "👩 Общий чекап (женщины 20–35)",
        "desc":  "Базовые анализы, УЗИ, какие специалисты нужны ежегодно и почему. Что смотреть при плановом осмотре.",
    },
    "checkup_thyroid": {
        "title": "🦋 Чекап щитовидки",
        "desc":  "Какие анализы сдать (не только ТТГ), как читать результаты, когда нужен эндокринолог и УЗИ.",
    },
    "checkup_fatigue": {
        "title": "😴 Чекап при хронической усталости",
        "desc":  "Ферритин, B12, витамин D, кортизол и другие — полный список с объяснением зачем каждый анализ.",
    },
    "checkup_gut": {
        "title": "🍽️ Чекап ЖКТ",
        "desc":  "Когда нужна гастроскопия, что сдать сначала, как различить функциональные и органические нарушения.",
    },
    "checkup_mental": {
        "title": "🧩 Чекап психического здоровья",
        "desc":  "Скрининговые шкалы тревоги и депрессии, к кому идти (психолог/психотерапевт/психиатр/нарколог/невролог) и в каких случаях.",
    },
}

PAV_QUESTION_TEXT = (
    "➕ <b>Блок про ПАВ</b>\n"
    "Употребляете ли вы психоактивные вещества?\n\n"
    "Отметь всё что подходит, затем нажми <b>«Готово»</b>\n"
    "Если ничего — нажми <b>«Не употребляю»</b>"
)

PAV_QUESTIONS = {
    "никотин":   "🚬 <b>Никотин:</b> что именно и сколько в день?\n<i>Например: сигареты — 1 пачка/день, вейп постоянно, 10 сигарет/день</i>",
    "алкоголь":  "🍷 <b>Алкоголь:</b> что и сколько употребляете?\n<i>Например: пиво 2–3 бутылки в день, вино по выходным, водка 100 г ежедневно</i>",
    "наркотики": "💊 <b>Наркотики:</b> что именно и как часто?\n<i>Например: каннабис ежедневно, стимуляторы по выходным</i>",
}

PAV_STATES = {
    "никотин":   PsychForm.pav_nicotine,
    "алкоголь":  PsychForm.pav_alcohol,
    "наркотики": PsychForm.pav_drugs,
}

PAV_KEYS = {
    "pav_nicotine": "никотин",
    "pav_alcohol":  "алкоголь",
    "pav_drugs":    "наркотики",
}

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ — общие
# ─────────────────────────────────────────
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(WELCOME, reply_markup=main_menu(), parse_mode="HTML")

async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(WELCOME, reply_markup=main_menu(), parse_mode="HTML")

async def cb_how_it_works(call: CallbackQuery):
    await call.message.edit_text(HOW_IT_WORKS, reply_markup=back_main_kb(), parse_mode="HTML")

async def cb_prices(call: CallbackQuery):
    await call.message.edit_text(PRICES_TEXT, reply_markup=back_main_kb(), parse_mode="HTML")

async def cb_checkups(call: CallbackQuery):
    await call.message.edit_text(
        "📋 <b>Готовые чекапы</b>\n\nВыбери нужный чекап — получишь PDF с конкретным списком анализов и обследований:",
        reply_markup=checkup_menu(),
        parse_mode="HTML",
    )

async def cb_buy_checkup(call: CallbackQuery, bot: Bot):
    key = call.data.replace("buy_", "")
    info = CHECKUP_DESCRIPTIONS.get(key)
    price = PRICES.get(key, 500)
    if not info:
        await call.answer("Ошибка")
        return

    # Уведомляем врача о покупке чекапа
    await bot.send_message(
        DOCTOR_CHAT_ID,
        f"🛒 <b>Покупка чекапа</b>\n\n"
        f"👤 @{call.from_user.username or '—'} (ID: {call.from_user.id})\n"
        f"📋 Чекап: {info['title']}\n"
        f"💰 Сумма: {price} руб\n\n"
        f"⚠️ Ожидает оплаты и скриншота",
        parse_mode="HTML",
    )

    text = (
        f"{info['title']}\n\n"
        f"{info['desc']}\n\n"
        f"💰 Цена: <b>{price} руб</b>\n\n"
        f"<b>Для оплаты:</b>\n"
        f"Переведи {price} руб на карту:\n"
        f"<code>{CARD_NUMBER}</code> — нажми и удержи чтобы скопировать\n"
        f"Получатель: {CARD_NAME}\n\n"
        f"После оплаты пришли скриншот сюда — чеклист придёт вам в лс от @qnbch, ожидайте 🧠"
    )
    await call.message.edit_text(text, reply_markup=back_main_kb(), parse_mode="HTML")

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ — ПСИХИАТРИЯ (6 вопросов + ПАВ-блок)
# ─────────────────────────────────────────
async def cb_start_psych(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(PsychForm.age_sex)
    await call.message.edit_text(
        "🧠 <b>Разбор жалоб — психиатрия/наркология</b>\n\n"
        "6 вопросов + блок про употребление веществ. Займёт 3–5 минут.\n\n"
        "<b>Вопрос 1/6</b>\nУкажи возраст и пол\n<i>Например: 28, женщина</i>",
        parse_mode="HTML",
    )

async def psych_age_sex(message: Message, state: FSMContext):
    await state.update_data(age_sex=message.text)
    await state.set_state(PsychForm.height_weight)
    await message.answer(
        "<b>Вопрос 2/6</b>\nРост и вес\n<i>Например: 165 см, 60 кг</i>",
        parse_mode="HTML",
    )

async def psych_height_weight(message: Message, state: FSMContext):
    await state.update_data(height_weight=message.text)
    await state.set_state(PsychForm.complaints)
    await message.answer(
        "<b>Вопрос 3/6</b>\nОпиши основные жалобы — что беспокоит?\n\n"
        "<i>Пиши свободно, чем подробнее — тем точнее маршрут</i>",
        parse_mode="HTML",
    )

async def psych_complaints(message: Message, state: FSMContext):
    await state.update_data(complaints=message.text)
    await state.set_state(PsychForm.duration)
    await message.answer(
        "<b>Вопрос 4/6</b>\nКак давно это беспокоит?",
        parse_mode="HTML",
    )

async def psych_duration(message: Message, state: FSMContext):
    await state.update_data(duration=message.text)
    await state.set_state(PsychForm.prev_doctors)
    await message.answer(
        "<b>Вопрос 5/6</b>\nК каким специалистам уже обращались и что они говорили?\n\n"
        "<i>Например: психиатр — сказал ВСД, психотерапевт — работали с тревогой, нарколог — кодировался.\n"
        "Если не обращались — «нет» или нажми «Пропустить»</i>",
        reply_markup=skip_kb(),
        parse_mode="HTML",
    )

async def psych_prev_doctors(message: Message, state: FSMContext):
    await state.update_data(prev_doctors=message.text)
    await state.set_state(PsychForm.medications)
    await message.answer(
        "<b>Вопрос 6/6</b>\nКакие препараты и БАДы принимаешь сейчас — и в каких дозировках?\n\n"
        "<i>Например: сертралин 50 мг, магний 400 мг.\n"
        "Если ничего — «нет» или нажми «Пропустить»</i>",
        reply_markup=skip_kb(),
        parse_mode="HTML",
    )

async def psych_medications(message: Message, state: FSMContext):
    await state.update_data(medications=message.text, pav_list=[])
    await state.set_state(PsychForm.pav_select)
    await message.answer(
        PAV_QUESTION_TEXT,
        reply_markup=pav_select_kb([]),
        parse_mode="HTML",
    )

# ─── ПАВ-блок ───

async def pav_toggle(call: CallbackQuery, state: FSMContext):
    """Переключение выбора вещества (мультиселект)"""
    data = await state.get_data()
    pav_list = list(data.get("pav_list", []))
    substance = PAV_KEYS[call.data]

    if substance in pav_list:
        pav_list.remove(substance)
    else:
        pav_list.append(substance)

    await state.update_data(pav_list=pav_list)
    selected_text = ", ".join(pav_list) if pav_list else "ничего не выбрано"
    await call.message.edit_text(
        PAV_QUESTION_TEXT + f"\n\n✓ Выбрано: <b>{selected_text}</b>",
        reply_markup=pav_select_kb(pav_list),
        parse_mode="HTML",
    )
    await call.answer()

async def pav_none(call: CallbackQuery, state: FSMContext):
    """Не употребляет — сразу к формату ответа"""
    await state.update_data(pav_list=[], pav_nicotine="—", pav_alcohol="—", pav_drugs="—", pav_duration="—")
    await state.set_state(PsychForm.answer_format)
    await call.message.edit_text(
        "✅ <b>Последний шаг</b>\n\nВ каком формате хочешь получить ответ?",
        reply_markup=format_kb(),
        parse_mode="HTML",
    )

async def pav_done(call: CallbackQuery, state: FSMContext):
    """Выбор сделан — задаём уточняющие вопросы по каждому веществу"""
    data = await state.get_data()
    pav_list = list(data.get("pav_list", []))
    if not pav_list:
        await call.answer("Выбери хотя бы одно вещество или нажми «Не употребляю»", show_alert=True)
        return
    await call.answer()
    await _ask_next_pav(call.message, state, pav_list, edit=True)

async def _ask_next_pav(message, state: FSMContext, remaining: list, edit: bool = False):
    """Задаёт уточняющий вопрос по первому веществу из списка; если список пуст — спрашивает длительность"""
    if not remaining:
        await state.set_state(PsychForm.pav_duration)
        text = "⏳ <b>Как долго употребляете?</b>\n<i>Например: курю 5 лет, пью алкоголь 3 года</i>"
        if edit:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")
        return

    substance = remaining[0]
    await state.set_state(PAV_STATES[substance])
    text = PAV_QUESTIONS[substance]
    if edit:
        await message.edit_text(text, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")

async def pav_nicotine_answer(message: Message, state: FSMContext):
    await state.update_data(pav_nicotine=message.text)
    data = await state.get_data()
    remaining = [x for x in data.get("pav_list", []) if x != "никотин"]
    await state.update_data(pav_list=remaining)
    await _ask_next_pav(message, state, remaining)

async def pav_alcohol_answer(message: Message, state: FSMContext):
    await state.update_data(pav_alcohol=message.text)
    data = await state.get_data()
    remaining = [x for x in data.get("pav_list", []) if x != "алкоголь"]
    await state.update_data(pav_list=remaining)
    await _ask_next_pav(message, state, remaining)

async def pav_drugs_answer(message: Message, state: FSMContext):
    await state.update_data(pav_drugs=message.text)
    data = await state.get_data()
    remaining = [x for x in data.get("pav_list", []) if x != "наркотики"]
    await state.update_data(pav_list=remaining)
    await _ask_next_pav(message, state, remaining)

async def pav_duration_answer(message: Message, state: FSMContext):
    await state.update_data(pav_duration=message.text)
    await state.set_state(PsychForm.answer_format)
    await message.answer(
        "✅ <b>Последний шаг</b>\n\nВ каком формате хочешь получить ответ?",
        reply_markup=format_kb(),
        parse_mode="HTML",
    )

# ─── Формат и срочность (психиатрия) ───

async def psych_format(call: CallbackQuery, state: FSMContext):
    fmt = "текстом" if call.data == "fmt_text" else "голосовым"
    await state.update_data(answer_format=fmt)
    await state.set_state(PsychForm.urgency)
    await call.message.edit_text(
        "⏱ <b>Выбери срок ответа:</b>\n\n"
        "<i>⚠️ Срочный ответ (2–3 часа) доступен только в рабочие часы: с 10:00 до 19:00</i>",
        reply_markup=urgency_kb(PRICES["psychiatry"]),
        parse_mode="HTML",
    )

async def psych_urgency(call: CallbackQuery, state: FSMContext, bot: Bot):
    is_urgent = call.data == "urg_urgent"
    base = PRICES["psychiatry"]
    price = base + URGENT_SURCHARGE if is_urgent else base
    urgency_text = "Срочно (2–3 часа)" if is_urgent else "Стандарт (24 часа)"
    await state.update_data(urgency=urgency_text, price=price)
    data = await state.get_data()

    doctor_msg = (
        f"🔔 <b>Новая заявка — Психиатрия/наркология</b>\n\n"
        f"👤 @{call.from_user.username or '—'} (ID: {call.from_user.id})\n"
        f"📊 Возраст/пол: {data.get('age_sex', '—')}\n"
        f"📏 Рост/вес: {data.get('height_weight', '—')}\n"
        f"💬 Жалобы: {data.get('complaints', '—')}\n"
        f"⏳ Длительность: {data.get('duration', '—')}\n"
        f"🏥 Специалисты и их мнение: {data.get('prev_doctors', '—')}\n"
        f"💊 Препараты и дозировки: {data.get('medications', '—')}\n\n"
        f"🚬 Никотин: {data.get('pav_nicotine', '—')}\n"
        f"🍷 Алкоголь: {data.get('pav_alcohol', '—')}\n"
        f"💊 Наркотики: {data.get('pav_drugs', '—')}\n"
        f"⏳ Как долго употребляет: {data.get('pav_duration', '—')}\n\n"
        f"📝 Формат ответа: {data.get('answer_format', '—')}\n"
        f"⏱ Срочность: {urgency_text}\n"
        f"💰 К оплате: {price} руб\n\n"
        f"⚠️ Ожидает подтверждения оплаты"
    )
    await bot.send_message(DOCTOR_CHAT_ID, doctor_msg, parse_mode="HTML")

    await call.message.edit_text(
        f"✅ <b>Анкета принята!</b>\n\n"
        f"Направление: Психиатрия/наркология\n"
        f"Срок: {urgency_text}\n"
        f"💰 <b>К оплате: {price} руб</b>\n\n"
        f"<b>Реквизиты для перевода:</b>\n"
        f"<code>{CARD_NUMBER}</code> — нажми и удержи чтобы скопировать\n"
        f"Получатель: {CARD_NAME}\n\n"
        f"После оплаты пришли сюда скриншот — ответ придёт вам в лс от @qnbch, ожидайте 🧠",
        reply_markup=back_main_kb(),
        parse_mode="HTML",
    )
    await state.clear()

# ─────────────────────────────────────────
# ХЕНДЛЕРЫ — ТЕРАПИЯ (7 вопросов)
# ─────────────────────────────────────────
async def cb_start_therapy(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(TherapyForm.age_sex)
    await call.message.edit_text(
        "🩺 <b>Разбор жалоб — терапия</b>\n\n"
        "7 вопросов, займёт 3–5 минут.\n\n"
        "<b>Вопрос 1/7</b>\nУкажи возраст и пол\n<i>Например: 32, женщина</i>",
        parse_mode="HTML",
    )

async def therapy_age_sex(message: Message, state: FSMContext):
    await state.update_data(age_sex=message.text)
    await state.set_state(TherapyForm.height_weight)
    await message.answer(
        "<b>Вопрос 2/7</b>\nРост и вес\n<i>Например: 165 см, 60 кг</i>",
        parse_mode="HTML",
    )

async def therapy_height_weight(message: Message, state: FSMContext):
    await state.update_data(height_weight=message.text)
    await state.set_state(TherapyForm.complaints)
    await message.answer(
        "<b>Вопрос 3/7</b>\nОпиши жалобы — что беспокоит?\n\n"
        "<i>Например: усталость, проблемы с ЖКТ, выпадение волос, набор веса и т.д.</i>",
        parse_mode="HTML",
    )

async def therapy_complaints(message: Message, state: FSMContext):
    await state.update_data(complaints=message.text)
    await state.set_state(TherapyForm.duration)
    await message.answer("<b>Вопрос 4/7</b>\nКак давно это беспокоит?", parse_mode="HTML")

async def therapy_duration(message: Message, state: FSMContext):
    await state.update_data(duration=message.text)
    await state.set_state(TherapyForm.prev_doctors)
    await message.answer(
        "<b>Вопрос 5/7</b>\nК каким специалистам уже обращались и что они говорили?\n\n"
        "<i>Например: терапевт — сказал в норме, гастроэнтеролог — гастрит.\n"
        "Если не обращались — «нет» или нажми «Пропустить»</i>",
        reply_markup=skip_kb(),
        parse_mode="HTML",
    )

async def therapy_prev_doctors(message: Message, state: FSMContext):
    await state.update_data(prev_doctors=message.text)
    await state.set_state(TherapyForm.medications)
    await message.answer(
        "<b>Вопрос 6/7</b>\nКакие препараты и БАДы принимаешь сейчас — и в каких дозировках?\n\n"
        "<i>Например: омепразол 20 мг, витамин D 2000 МЕ.\n"
        "Если ничего — «нет» или нажми «Пропустить»</i>",
        reply_markup=skip_kb(),
        parse_mode="HTML",
    )

async def therapy_medications(message: Message, state: FSMContext):
    await state.update_data(medications=message.text)
    await state.set_state(TherapyForm.answer_format)
    await message.answer(
        "<b>Вопрос 7/7</b>\nВ каком формате хочешь получить ответ?",
        reply_markup=format_kb(),
        parse_mode="HTML",
    )

async def therapy_format(call: CallbackQuery, state: FSMContext):
    fmt = "текстом" if call.data == "fmt_text" else "голосовым"
    await state.update_data(answer_format=fmt)
    await state.set_state(TherapyForm.urgency)
    await call.message.edit_text(
        "⏱ <b>Выбери срок ответа:</b>\n\n"
        "<i>⚠️ Срочный ответ (2–3 часа) доступен только в рабочие часы: с 10:00 до 19:00</i>",
        reply_markup=urgency_kb(PRICES["therapy"]),
        parse_mode="HTML",
    )

async def therapy_urgency(call: CallbackQuery, state: FSMContext, bot: Bot):
    is_urgent = call.data == "urg_urgent"
    base = PRICES["therapy"]
    price = base + URGENT_SURCHARGE if is_urgent else base
    urgency_text = "Срочно (2–3 часа)" if is_urgent else "Стандарт (24 часа)"
    await state.update_data(urgency=urgency_text, price=price)
    data = await state.get_data()

    doctor_msg = (
        f"🔔 <b>Новая заявка — Терапия</b>\n\n"
        f"👤 @{call.from_user.username or '—'} (ID: {call.from_user.id})\n"
        f"📊 Возраст/пол: {data.get('age_sex', '—')}\n"
        f"📏 Рост/вес: {data.get('height_weight', '—')}\n"
        f"💬 Жалобы: {data.get('complaints', '—')}\n"
        f"⏳ Длительность: {data.get('duration', '—')}\n"
        f"🏥 Специалисты и их мнение: {data.get('prev_doctors', '—')}\n"
        f"💊 Препараты и дозировки: {data.get('medications', '—')}\n\n"
        f"📝 Формат ответа: {data.get('answer_format', '—')}\n"
        f"⏱ Срочность: {urgency_text}\n"
        f"💰 К оплате: {price} руб\n\n"
        f"⚠️ Ожидает подтверждения оплаты"
    )
    await bot.send_message(DOCTOR_CHAT_ID, doctor_msg, parse_mode="HTML")

    await call.message.edit_text(
        f"✅ <b>Анкета принята!</b>\n\n"
        f"Направление: Терапия\n"
        f"Срок: {urgency_text}\n"
        f"💰 <b>К оплате: {price} руб</b>\n\n"
        f"<b>Реквизиты для перевода:</b>\n"
        f"<code>{CARD_NUMBER}</code> — нажми и удержи чтобы скопировать\n"
        f"Получатель: {CARD_NAME}\n\n"
        f"После оплаты пришли сюда скриншот — ответ придёт вам в лс от @qnbch, ожидайте 🧠",
        reply_markup=back_main_kb(),
        parse_mode="HTML",
    )
    await state.clear()

# ─────────────────────────────────────────
# ХЕНДЛЕР — СКРИНШОТ ОПЛАТЫ
# ─────────────────────────────────────────
async def payment_screenshot(message: Message, bot: Bot):
    """Пересылаем скриншот оплаты врачу"""
    await bot.forward_message(DOCTOR_CHAT_ID, message.chat.id, message.message_id)
    await bot.send_message(
        DOCTOR_CHAT_ID,
        f"👆 Скриншот оплаты от @{message.from_user.username or '—'} (ID: {message.from_user.id})",
    )
    await message.answer(
        "📨 Скриншот получен! Ответ придёт вам в лс от @qnbch, ожидайте 🧠"
    )

# ─────────────────────────────────────────
# РЕГИСТРАЦИЯ ХЕНДЛЕРОВ
# ─────────────────────────────────────────
def register_handlers(dp: Dispatcher):
    # Команда старт
    dp.message.register(cmd_start, CommandStart())

    # Навигация
    dp.callback_query.register(cb_back_main,    F.data == "back_main")
    dp.callback_query.register(cb_how_it_works, F.data == "how_it_works")
    dp.callback_query.register(cb_prices,       F.data == "prices")
    dp.callback_query.register(cb_checkups,     F.data == "checkups")
    dp.callback_query.register(cb_buy_checkup,  F.data.startswith("buy_checkup_"))

    # ── Психиатрия ──
    dp.callback_query.register(cb_start_psych,     F.data == "start_psych")
    dp.message.register(psych_age_sex,             PsychForm.age_sex)
    dp.message.register(psych_height_weight,       PsychForm.height_weight)
    dp.message.register(psych_complaints,          PsychForm.complaints)
    dp.message.register(psych_duration,            PsychForm.duration)
    dp.message.register(psych_prev_doctors,        PsychForm.prev_doctors)
    dp.message.register(psych_medications,         PsychForm.medications)
    # ПАВ-блок
    dp.callback_query.register(pav_toggle, PsychForm.pav_select, F.data.in_({"pav_nicotine", "pav_alcohol", "pav_drugs"}))
    dp.callback_query.register(pav_none,   PsychForm.pav_select, F.data == "pav_none")
    dp.callback_query.register(pav_done,   PsychForm.pav_select, F.data == "pav_done")
    dp.message.register(pav_nicotine_answer, PsychForm.pav_nicotine)
    dp.message.register(pav_alcohol_answer,  PsychForm.pav_alcohol)
    dp.message.register(pav_drugs_answer,    PsychForm.pav_drugs)
    dp.message.register(pav_duration_answer, PsychForm.pav_duration)
    # Финал
    dp.callback_query.register(psych_format,  PsychForm.answer_format, F.data.in_({"fmt_text", "fmt_voice"}))
    dp.callback_query.register(psych_urgency, PsychForm.urgency,       F.data.in_({"urg_standard", "urg_urgent"}))

    # ── Терапия ──
    dp.callback_query.register(cb_start_therapy,   F.data == "start_therapy")
    dp.message.register(therapy_age_sex,           TherapyForm.age_sex)
    dp.message.register(therapy_height_weight,     TherapyForm.height_weight)
    dp.message.register(therapy_complaints,        TherapyForm.complaints)
    dp.message.register(therapy_duration,          TherapyForm.duration)
    dp.message.register(therapy_prev_doctors,      TherapyForm.prev_doctors)
    dp.message.register(therapy_medications,       TherapyForm.medications)
    dp.callback_query.register(therapy_format,     TherapyForm.answer_format, F.data.in_({"fmt_text", "fmt_voice"}))
    dp.callback_query.register(therapy_urgency,    TherapyForm.urgency,       F.data.in_({"urg_standard", "urg_urgent"}))

    # Скриншот оплаты (в любом состоянии)
    dp.message.register(payment_screenshot, F.photo)

# ─────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    redis_url = os.getenv("REDIS_URL", "")
    storage = RedisStorage.from_url(redis_url) if redis_url else MemoryStorage()
    dp = Dispatcher(storage=storage)
    register_handlers(dp)
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
