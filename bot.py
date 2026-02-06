import asyncio
import logging
import os
import fitz  # PyMuPDF
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from langchain_community.chat_models import GigaChat

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = 'токен бота'
GIGACHAT_CREDENTIALS = 'токен из GIGACHAT'
ADMIN_ID = id профиля администратора бота

MANUALS_DIR = "manuals"
os.makedirs(MANUALS_DIR, exist_ok=True)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
giga = GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl_certs=False)

# Хранилище временных состояний (в продакшене лучше использовать FSM/Redis)
user_states = {}

logging.basicConfig(level=logging.INFO)

# --- КЛАВИАТУРЫ ---

def get_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 База инструкций", callback_data="list_files")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="ask_support")]
    ])

def get_files_kb():
    files = [f for f in os.listdir(MANUALS_DIR) if f.endswith(".pdf")]
    buttons = [[InlineKeyboardButton(text=f"📄 {f[:40]}", callback_data=f"open_{f[:40]}")] for f in files]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_reply_kb(user_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить пользователю", callback_data=f"reply_to_{user_id}")]
    ])

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_best_context(query):
    files = [f for f in os.listdir(MANUALS_DIR) if f.endswith(".pdf")]
    query_words = [w.lower() for w in query.split() if len(w) > 3]
    all_results = []
    for filename in files:
        try:
            doc = fitz.open(os.path.join(MANUALS_DIR, filename))
            for page in doc:
                text = page.get_text("text")
                score = sum(3 if word in text.lower() else 0 for word in query_words)
                if score > 2:
                    all_results.append({"text": text[:4000], "page_obj": page, "source": filename, "score": score, "page_num": page.number + 1})
        except: continue
    if not all_results: return None
    all_results.sort(key=lambda x: x['score'], reverse=True)
    return all_results[0]

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_states.pop(message.from_user.id, None)
    await message.answer(
        f"🛠 **Система поддержки ДДС**\n\nЗдравствуйте, {message.from_user.first_name}!\n"
        "Вы можете задать вопрос и бот выдаст Вам ответ из руководства.",
        reply_markup=get_main_kb(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    user_states.pop(callback.from_user.id, None)
    await callback.message.edit_text("🛠 **Главное меню**", reply_markup=get_main_kb())

@dp.callback_query(F.data == "list_files")
async def show_manuals(callback: types.CallbackQuery):
    await callback.message.edit_text("📂 Выберите файл для просмотра:", reply_markup=get_files_kb())

@dp.callback_query(F.data == "ask_support")
async def support_init(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = 'waiting_support_msg'
    await callback.message.edit_text(
        "📝 **Опишите вашу проблему одним сообщением:**\n\nАдминистрация бота получит ваш запрос и ответит прямо здесь.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]])
    )

# Кнопка ответа для админа
@dp.callback_query(F.data.startswith("reply_to_"))
async def admin_reply_start(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Ошибка")

    target_user_id = int(callback.data.replace("reply_to_", ""))
    user_states[ADMIN_ID] = f'typing_reply_{target_user_id}'
    await callback.message.answer(f"✍️ Введите ответ для пользователя (ID: {target_user_id}):")
    await callback.answer()

@dp.message(F.text)
async def handle_all_messages(message: types.Message):
    state = user_states.get(message.from_user.id)

    # 1. Режим ожидания вопроса от пользователя
    if state == 'waiting_support_msg':
        await bot.send_message(
            ADMIN_ID,
            f"🔔 **НОВЫЙ ВОПРОС**\n👤 От: {message.from_user.full_name}\n🆔 ID: {message.from_user.id}\n\n💬 {message.text}",
            reply_markup=get_admin_reply_kb(message.from_user.id)
        )
        user_states.pop(message.from_user.id)
        await message.answer("✅ Сообщение отправлено администрации бота. Ожидайте ответа.", reply_markup=get_main_kb())
        return

    # 2. Режим написания ответа админом
    if state and state.startswith('typing_reply_'):
        target_id = int(state.replace('typing_reply_', ''))
        try:
            await bot.send_message(target_id, f"👨‍🔧 **Ответ администрации бота:**\n\n{message.text}")
            await message.answer("🚀 Ответ успешно доставлен!")
        except Exception as e:
            await message.answer(f"❌ Не удалось отправить ответ: {e}")
        user_states.pop(ADMIN_ID)
        return

    # 3. Стандартный поиск через ИИ
    wait_msg = await message.answer("🔍 **Анализирую техническую документацию...**")
    context = get_best_context(message.text)

    if not context:
        return await wait_msg.edit_text(
            "❌ **В официальных руководствах нет информации по этому запросу.**\n\n"
            "Попробуйте:\n"
            "• Проверить правильность написания модели\n"
            "• Использовать другие ключевые слова\n"
            "• Нажать кнопку **'Написать в поддержку'**",
            reply_markup=get_main_kb()
        )

    #ПРОМПТ ДЛЯ GIGACHAT
    prompt = (
        "ТЫ: Ведущий инженер техподдержки компании ДДС. Твоя речь профессиональна, точна и лаконична.\n"
        "ЗАДАЧА: Ответить на вопрос рабочего, используя только предоставленный ТЕКСТ ИЗ ИНСТРУКЦИИ.\n\n"
        "ПРАВИЛА ОТВЕТА:\n"
        "1. Начни ответ с прямой фразы: 'Согласно инструкции к [название файла]...'\n"
        "2. Если в тексте есть пошаговый алгоритм — представь его нумерованным списком.\n"
        "3. Важные параметры (давление, напряжение, названия узлов) выделяй ЖИРНЫМ шрифтом.\n"
        "4. Если в тексте НЕТ прямого ответа, напиши: 'В предоставленном фрагменте документации точных данных нет, обратитесь к инженеру через кнопку Поддержка'.\n"
        "5. Запрещено использовать свои знания из интернета. Только приложенный текст!\n\n"
        f"ИСТОЧНИК ТЕКСТА:\n{context['text']}\n\n"
        f"ВОПРОС ПОЛЬЗОВАТЕЛЯ: {message.text}\n\n"
        "ТВОЙ ИНЖЕНЕРНЫЙ ОТВЕТ:"
    )

    try:
        # Вызываем GigaCha
        res = giga.invoke(prompt)
        response = res.content

        page = context['page_obj']
        # Увеличиваем четкость скриншота (zoom=2.0)
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        photo = BufferedInputFile(pix.tobytes("png"), filename="manual_page.png")

        await message.answer_photo(
            photo=photo,
            caption=(
                f"📖 **Файл:** `{context['source']}`\n"
                f"📄 **Страница:** {context['page_num']}\n\n"
                f"{response[:900]}"
            ),
            reply_markup=get_main_kb(),
            parse_mode="Markdown"
        )
        await wait_msg.delete()

    except Exception as e:
        logging.error(f"GigaChat Error: {e}")
        await wait_msg.edit_text("⚠️ **Ошибка. Попробуйте позже.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":

    asyncio.run(main())
