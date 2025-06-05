import discord
from discord import app_commands
from discord.ext import tasks
from flask import Flask
from threading import Thread
import asyncio
import os
import json
import random
import string

# ------------- Настройки -------------

# Интенты: нужны для слежения за участниками и содержимым сообщений
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

# Клиент и деревo команд
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ID сервера SOLO
GUILD_ID = 1374663288134307891
GUILD = discord.Object(id=GUILD_ID)

# Каналы
ALLIANCE_CHANNEL_ID = 1378520564066685001
STAFF_CHANNEL_ID = 1378524871117766766
PING_CHANNEL_ID = 1378925142738075688
VERIF_CATEGORY_ID = 1378925066779099317

# Роли
ROLE_UNVERIFIED = 1375697204223676477
ROLE_VERIFIED_1 = 1375082315365093498
ROLE_VERIFIED_2 = 1375696805945282591

# Ранги стаффа в нужном порядке
STAFF_RANKS = ['овнер', 'со-овнер', 'админ', 'модератор', 'инвайтер']

# Цвет чёрный
COLOR_BLACK = 0x000000

# Файлы для хранения данных
ALLIANCE_FILE = "alliances.json"
STAFF_FILE = "staff.json"

# Символы для генерации кода (буквы + цифры)
CHAR_POOL = string.ascii_letters + string.digits

# ------------- Глобальные структуры -------------

# Данные альянсов: { «тег»: { "description": ..., "contact": ... } }
alliance_data: dict[str, dict[str, str]] = {}

# Данные стаффа: { «ранг»: [ "ник1", "ник2", ... ] }
staff_data: dict[str, list[str]] = {rank: [] for rank in STAFF_RANKS}

# Сообщения-embed (для редактирования)
alliance_message: discord.Message | None = None
staff_message: discord.Message | None = None

# Ожидающие верификацию: 
# { member_id: { "channel_id": int, "code": str, "attempts": int } }
pending_verifications: dict[int, dict[str, object]] = {}


# ------------- Утилиты для JSON -------------

def load_alliances():
    global alliance_data
    try:
        with open(ALLIANCE_FILE, "r", encoding="utf-8") as f:
            alliance_data = json.load(f)
    except FileNotFoundError:
        alliance_data = {}
    except json.JSONDecodeError:
        alliance_data = {}

def save_alliances():
    with open(ALLIANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(alliance_data, f, ensure_ascii=False, indent=2)

def load_staff():
    global staff_data
    try:
        with open(STAFF_FILE, "r", encoding="utf-8") as f:
            staff_data = json.load(f)
            # Убедимся, что все ранги есть
            for rank in STAFF_RANKS:
                staff_data.setdefault(rank, [])
    except FileNotFoundError:
        staff_data = {rank: [] for rank in STAFF_RANKS}
    except json.JSONDecodeError:
        staff_data = {rank: [] for rank in STAFF_RANKS}

def save_staff():
    with open(STAFF_FILE, "w", encoding="utf-8") as f:
        json.dump(staff_data, f, ensure_ascii=False, indent=2)


# ------------- Embed-строители -------------
def make_alliance_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🏰 Альянсы клана SOLO",
        description="Здесь перечислены все альянсы. (Обновляется вручную командами)",
        color=COLOR_BLACK
    )
    if not alliance_data:
        embed.add_field(name="—", value="Альянсы отсутствуют.", inline=False)
    else:
        for tag, info in alliance_data.items():
            contact_mention = f"<@{info['contact']}>"
            desc = f"{info['description']}\n**Контакт:** {contact_mention}"
            embed.add_field(name=f"🔖 {tag}", value=desc, inline=False)
    embed.set_footer(text="Клан SOLO | Альянсы")
    return embed

def make_staff_embed() -> discord.Embed:
    embed = discord.Embed(
        title="👥 Стафф клана SOLO",
        description="Список участников стаффа по рангам.",
        color=COLOR_BLACK
    )
    for rank in STAFF_RANKS:
        members = staff_data.get(rank, [])
        value = "\n".join(f"• {m}" for m in members) if members else "—"
        embed.add_field(name=rank.capitalize(), value=value, inline=False)
    embed.set_footer(text="Клан SOLO | Стафф")
    return embed


# ------------- Инициализация и обновление embed-сообщений -------------

async def update_alliance_message():
    global alliance_message
    channel = bot.get_channel(ALLIANCE_CHANNEL_ID)
    if channel is None:
        return
    embed = make_alliance_embed()
    if alliance_message:
        try:
            await alliance_message.edit(embed=embed)
        except discord.NotFound:
            alliance_message = await channel.send(embed=embed)
    else:
        alliance_message = await channel.send(embed=embed)

async def update_staff_message():
    global staff_message
    channel = bot.get_channel(STAFF_CHANNEL_ID)
    if channel is None:
        return
    embed = make_staff_embed()
    if staff_message:
        try:
            await staff_message.edit(embed=embed)
        except discord.NotFound:
            staff_message = await channel.send(embed=embed)
    else:
        staff_message = await channel.send(embed=embed)

async def init_messages():
    # Дадим боту время подключиться и получить каналы
    await asyncio.sleep(5)
    await update_alliance_message()
    await update_staff_message()


# ------------- Проверка прав администратора -------------

def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.administrator
    return app_commands.check(predicate)


# ------------- Слэш-команды для альянсов -------------

# Убираем неправильный @bot.slash_command и делаем так:

@tree.command(
    name="добавить_альянс",
    description="Добавить альянс (тег, описание, контакт ID)",
    guild=GUILD
)
@app_commands.describe(
    тег="Тег альянса (без пробелов)",
    описание="Описание альянса",
    контакт="ID пользователя без @"
)
@app_commands.checks.has_permissions(administrator=True)
async def добавить_альянс(
    interaction: discord.Interaction,
    тег: str,
    описание: str,
    контакт: str
):
    # Проверяем, что контакт — это только цифры
    if not контакт.isdigit():
        await interaction.response.send_message(
            "❌ Укажи **только ID пользователя**, без @.", ephemeral=True
        )
        return

    emoji = "🏰"
    mention = f"<@{контакт}>"
    alliance_data[тег] = {
        "description": описание,
        "contact": контакт
    }
    save_alliances()
    await update_alliance_message()
    await interaction.response.send_message(f"✅ Альянс `{тег}` добавлен.", ephemeral=True)


@tree.command(
    name="удалить_альянс",
    description="Удалить альянс по тегу",
    guild=GUILD
)
@app_commands.describe(
    тег="Тег альянса для удаления"
)
@app_commands.checks.has_permissions(administrator=True)
async def удалить_альянс(
    interaction: discord.Interaction,
    тег: str
):
    if тег in alliance_data:
        del alliance_data[тег]
        save_alliances()
        await update_alliance_message()
        await interaction.response.send_message("❌ Альянс удалён.", ephemeral=True)
    else:
        await interaction.response.send_message("🚫 Альянс не найден.", ephemeral=True)


# ------------- Слэш-команды для стаффа -------------
@tree.command(
    name="добавить_стафф",
    description="Добавить стафф (ранг: овнер, со-овнер, админ, модератор, инвайтер)",
    guild=GUILD
)
@app_commands.describe(
    ник="Ник стаффа",
    ранг="Ранг стаффа"
)
@app_commands.checks.has_permissions(administrator=True)
async def добавить_стафф(
    interaction: discord.Interaction,
    ник: str,
    ранг: str
):
    ранг_lower = ранг.lower()
    if ранг_lower not in STAFF_RANKS:
        await interaction.response.send_message(
            f"🚫 Некорректный ранг. Выберите один из: {', '.join(STAFF_RANKS)}.", 
            ephemeral=True
        )
        return

    if ник in staff_data[ранг_lower]:
        await interaction.response.send_message("⚠️ Этот ник уже в списке.", ephemeral=True)
        return

    staff_data[ранг_lower].append(ник)
    save_staff()
    await update_staff_message()
    await interaction.response.send_message("✅ Стафф добавлен.", ephemeral=True)

@tree.command(
    name="удалить_стафф",
    description="Удалить стаффа по нику",
    guild=GUILD
)
@app_commands.describe(
    ник="Ник стаффа для удаления"
)
@app_commands.checks.has_permissions(administrator=True)
async def удалить_стафф(
    interaction: discord.Interaction,
    ник: str
):
    found = False
    for rank in STAFF_RANKS:
        if ник in staff_data.get(rank, []):
            staff_data[rank].remove(ник)
            found = True
            break
    if found:
        save_staff()
        await update_staff_message()
        await interaction.response.send_message("❌ Стафф удалён.", ephemeral=True)
    else:
        await interaction.response.send_message("🚫 Стафф не найден.", ephemeral=True)


# ------------- Верификация при входе -------------

@bot.event
async def on_member_join(member: discord.Member):
    if member.guild.id != GUILD_ID:
        return

    # Выдать роль "неверифицирован"
    try:
        await member.add_roles(discord.Object(id=ROLE_UNVERIFIED))
    except:
        pass

    # Пинг в канале, затем удаление
    ping_channel = bot.get_channel(PING_CHANNEL_ID)
    if ping_channel:
        msg = await ping_channel.send(f"{member.mention} Пожалуйста, пройди верификацию.")
        # Удаляем сразу же
        await msg.delete()

    # Создаём приватный канал для верификации
    category = bot.get_channel(VERIF_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        return

    overwrites = {
        member.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        member.guild.me: discord.PermissionOverwrite(view_channel=True)
    }
    chan_name = f"verify-{member.id}"
    verify_channel = await category.create_text_channel(
        name=chan_name,
        overwrites=overwrites,
        reason="Канал верификации"
    )
    # Включаем медленный режим 5 секунд
    await verify_channel.edit(slowmode_delay=5)

    # Генерируем код из 60 символов
    code = ''.join(random.choice(CHAR_POOL) for _ in range(60))
    pending_verifications[member.id] = {
        "channel_id": verify_channel.id,
        "code": code,
        "attempts": 0
    }

    # Отправляем embed-инструкцию
    embed = discord.Embed(
        title="🛡️ Верификация участника",
        description=(
            f"{member.mention}, тебе открыт **приватный канал** для прохождения верификации.\n\n"
            f"Введи этот код **точно** как он есть:\n```{code}```\n\n"
            f"❗ У тебя **5 попыток**. Если не получится — бот удалит канал и создаст новый с другим кодом."
        ),
        color=COLOR_BLACK
    )
    embed.set_footer(text="SOLO | Верификация")
    await verify_channel.send(embed=embed)
    @bot.event
    async def on_message(message: discord.Message):
        # Не реагировать на бота самого
        if message.author.bot:
            return

        # -------- Автоответы (включая "неактив" и "привет") --------
        if message.guild and message.guild.id == GUILD_ID:
            content = message.content.lower()
            # Проверка подстрок
            if "неактив" in content:
                await message.channel.send("так зайди в игру фрик❤️")
            elif "привет" in content:
                await message.channel.send("Привет!")
            elif content == "свага?":
                await message.channel.send("Имеется✅")
            elif content == "дрейк":
                await message.channel.send("Нет, диоген😡")
            elif content == "иваново":
                await message.channel.send("Деревня🌚")

        # -------- Обработка сообщений в канале верификации --------
        author_id = message.author.id
        if author_id in pending_verifications:
            state = pending_verifications[author_id]
            chan_id = state["channel_id"]
            if message.channel.id == chan_id:
                code_correct = state["code"]
                if message.content.strip() == code_correct:
                    # Успешная верификация
                    member = message.author
                    # Удаляем неверифицированную роль
                    try:
                        await member.remove_roles(discord.Object(id=ROLE_UNVERIFIED))
                    except:
                        pass
                    # Выдаем роли верифицированного
                    try:
                        await member.add_roles(discord.Object(id=ROLE_VERIFIED_1))
                        await member.add_roles(discord.Object(id=ROLE_VERIFIED_2))
                    except:
                        pass
                    # Удаляем канал
                    try:
                        chan = bot.get_channel(chan_id)
                        if chan:
                            await chan.delete()
                    except:
                        pass
                    # Удаляем из ожидания
                    del pending_verifications[author_id]
                    return


            else:
                # Неправильный код
                state["attempts"] += 1
                if state["attempts"] >= 5:
                    # Удаляем старый канал
                    old_chan = bot.get_channel(chan_id)
                    try:
                        if old_chan:
                            await old_chan.delete()
                    except:
                        pass
                    # Создаём новый канал и новый код
                    member = message.author
                    category = bot.get_channel(VERIF_CATEGORY_ID)
                    if isinstance(category, discord.CategoryChannel):
                        overwrites = {
                            member.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                            member.guild.me: discord.PermissionOverwrite(view_channel=True)
                        }
                        chan_name = f"verify-{member.id}"
                        verify_channel = await category.create_text_channel(
                            name=chan_name,
                            overwrites=overwrites,
                            reason="Перегенерация канала верификации"
                        )
                        await verify_channel.edit(slowmode_delay=5)
                        # Новый код
                        new_code = ''.join(random.choice(CHAR_POOL) for _ in range(60))
                        pending_verifications[author_id] = {"channel_id": verify_channel.id, "code": new_code, "attempts": 0}
                        await verify_channel.send(
                            f"{member.mention} Введён неверный код 5 раз. Вот новый код:\n\n{new_code}```"
                        )
                else:
                    # Ещё есть попытки
                    remaining = 5 - state["attempts"]
                    await message.channel.send(f"Неправильный код. Осталось попыток: {remaining}")
                return

    # -------- Обработка других сообщений (не верификация) --------
    # Слэш-команды обрабатываются автоматически, не нужно ничего делать здесь.


# ------------- Ивент on_ready -------------

@bot.event
async def on_ready():
    # Загрузка данных из JSON
    load_alliances()
    load_staff()

    # Инициализация embed-сообщений
    await init_messages()

    # Синхронизация слэш-команд только для указанного сервера
    await tree.sync(guild=GUILD)
    print(f"Бот запущен как {bot.user}. Слэш-команды синхронизированы.")


# ------------- Flask keep-alive для Replit -------------

app = Flask("")

@app.route("/")
def home():
    return "Бот SOLO работает 24/7!"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    server = Thread(target=run)
    server.start()

keep_alive()

# ------------- Запуск бота -------------

# Токен хранится в Secrets → переменная TOKEN
bot.run(os.getenv("TOKEN"))