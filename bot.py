import html
import logging
import os

from telegram import Update, InlineKeyboardButton as Btn, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))


# ---------- вспомогательные функции ----------

async def is_subscribed(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    try:
        member = await bot.get_chat_member(config.CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Не удалось проверить подписку: {e}")
        return False


async def send_screen(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                      text: str, kb: InlineKeyboardMarkup, photo=None) -> None:
    """Удаляет старый экран (и альбом) и отправляет новый.
    photo: None, одна картинка (путь/ссылка) или список картинок (альбом до 10 шт.)."""
    chat_id = update.effective_chat.id
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass
        try:
            await q.message.delete()
        except Exception:
            pass

    # убрать альбом от прошлого экрана
    for mid in ctx.user_data.pop("album", []):
        try:
            await ctx.bot.delete_message(chat_id, mid)
        except Exception:
            pass

    photos = photo if isinstance(photo, (list, tuple)) else ([photo] if photo else [])

    # одна картинка — подпись и кнопки прямо под ней
    if len(photos) == 1:
        p = photos[0]
        try:
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    await ctx.bot.send_photo(chat_id, f, caption=text,
                                             parse_mode="HTML", reply_markup=kb)
            else:
                await ctx.bot.send_photo(chat_id, p, caption=text,
                                         parse_mode="HTML", reply_markup=kb)
            return
        except Exception as e:
            logger.error(f"Не удалось отправить фото: {e}")

    # несколько картинок — альбом, а ниже сообщение с текстом и кнопками
    elif len(photos) > 1:
        files = []
        try:
            media = []
            for p in photos[:10]:
                if os.path.isfile(p):
                    f = open(p, "rb")
                    files.append(f)
                    media.append(InputMediaPhoto(f))
                else:
                    media.append(InputMediaPhoto(p))
            msgs = await ctx.bot.send_media_group(chat_id, media)
            ctx.user_data["album"] = [m.message_id for m in msgs]
        except Exception as e:
            logger.error(f"Не удалось отправить альбом: {e}")
        finally:
            for f in files:
                f.close()

    await ctx.bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [Btn("🎮 Проекты", callback_data="cat:projects"),
         Btn("🛠 Моды", callback_data="cat:mods")],
        [Btn("⚙️ Разработка", callback_data="cat:dev")],
        [Btn("💬 Отзывы", url=config.REVIEWS_LINK),
         Btn("📢 Канал", url=config.CHANNEL_LINK)],
        [Btn("🆘 Поддержка", callback_data="support")],
    ])


async def guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка обязательной подписки. False — пользователь не подписан."""
    if await is_subscribed(ctx.bot, update.effective_user.id):
        return True
    kb = InlineKeyboardMarkup([
        [Btn("📢 Подписаться", url=config.CHANNEL_LINK)],
        [Btn("✅ Я подписался", callback_data="check_sub")],
    ])
    await send_screen(
        update, ctx,
        "🔒 Чтобы пользоваться ботом, подпишись на наш канал, "
        "а затем нажми «Я подписался».",
        kb,
    )
    return False


def find_item(cat_key: str, item_id: str):
    cat = config.CATALOGS.get(cat_key)
    if not cat:
        return None
    for item in cat["items"]:
        if item["id"] == item_id:
            return item
    return None


# ---------- обработчики ----------

async def show_main(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_screen(update, ctx,
                      config.START_TEXT.format(name=config.PROJECT_NAME),
                      main_menu())


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await guard(update, ctx):
        await show_main(update, ctx)


async def menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await guard(update, ctx):
        await show_main(update, ctx)


async def check_sub(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if await is_subscribed(ctx.bot, q.from_user.id):
        await show_main(update, ctx)
    else:
        await q.answer("❌ Ты ещё не подписан на канал", show_alert=True)


async def category(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, ctx):
        return
    key = update.callback_query.data.split(":")[1]
    cat = config.CATALOGS.get(key)
    if not cat:
        return
    rows = [[Btn(i["name"], callback_data=f"item:{key}:{i['id']}")]
            for i in cat["items"]]
    rows.append([Btn("⬅️ Назад", callback_data="menu")])
    await send_screen(update, ctx, cat["title"], InlineKeyboardMarkup(rows))


async def item(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, ctx):
        return
    _, key, item_id = update.callback_query.data.split(":")
    it = find_item(key, item_id)
    if not it:
        return
    text = (f"<b>{it['name']}</b>\n\n{it['desc']}\n\n"
            f"💰 Цена: <b>{it['price']}</b>")
    kb = InlineKeyboardMarkup([
        [Btn("🛒 Заказать", callback_data=f"buy:{key}:{item_id}")],
        [Btn("⬅️ Назад", callback_data=f"cat:{key}")],
    ])
    await send_screen(update, ctx, text, kb, photo=it.get("photo"))


async def buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, ctx):
        return
    _, key, item_id = update.callback_query.data.split(":")
    it = find_item(key, item_id)
    if not it:
        return
    user = update.effective_user
    order = (
        "🛒 <b>Новый заказ!</b>\n\n"
        f"👤 {html.escape(user.full_name)}\n"
        f"🔗 @{user.username or '—'}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"📌 {html.escape(it['name'])} — {html.escape(str(it['price']))}"
    )
    try:
        await ctx.bot.send_message(ADMIN_ID, order, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка отправки заказа: {e}")

    kb = InlineKeyboardMarkup([
        [Btn("✉️ Написать продавцу", url=f"https://t.me/{config.SUPPORT_USERNAME}")],
        [Btn("⬅️ В меню", callback_data="menu")],
    ])
    await send_screen(
        update, ctx,
        f"✅ Заявка на <b>{it['name']}</b> отправлена!\n\n"
        f"Для оплаты и деталей напиши: @{config.SUPPORT_USERNAME}",
        kb,
    )


async def support(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, ctx):
        return
    kb = InlineKeyboardMarkup([
        [Btn("✉️ Написать в поддержку", url=f"https://t.me/{config.SUPPORT_USERNAME}")],
        [Btn("⬅️ Назад", callback_data="menu")],
    ])
    await send_screen(
        update, ctx,
        f"🆘 <b>Поддержка</b>\n\nПо любым вопросам пиши: @{config.SUPPORT_USERNAME}",
        kb,
    )


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_sub, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(category, pattern="^cat:"))
    app.add_handler(CallbackQueryHandler(item, pattern="^item:"))
    app.add_handler(CallbackQueryHandler(buy, pattern="^buy:"))
    app.add_handler(CallbackQueryHandler(support, pattern="^support$"))

    logger.info("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
