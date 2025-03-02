from flask import Flask, request, render_template, jsonify
import requests
from mistralai import Mistral
import io
import base64
import sqlite3
import os
import datetime
import json

app = Flask(__name__)

# Получение API ключа
MISTRAL_API_KEY = "cnYW87vD671nFClyTHkFEVOFYSz4FE3m"

SYSTEM_PROMPT = """
Ты — ИИ для анализа мемов и изображений. 
Твоя задача — кратко описать, что изображено на картинке, объяснить, 
почему это может быть популярным мемом, и учитывать культурный контекст, 
особенно для российских мемов. 
Если изображение содержит 18+ контент, напиши: Это изображение не подходит для анализа.
Четко и кратко и ясно отвечай. Всегда только на русском языке
Без лишнего
"""

# Инициализация клиента Mistral
model = "pixtral-12b-2409"
client = Mistral(api_key=MISTRAL_API_KEY)

# Путь к базе данных
DB_PATH = 'memes.db'


# Вспомогательные функции для работы с базой данных
def format_date(date_str):
    """Форматирует дату из базы данных для отображения"""
    if not date_str:
        return "Неизвестно"
    try:
        date = datetime.datetime.fromisoformat(date_str)
        return date.strftime('%d.%m.%Y')
    except:
        return date_str


def get_db_connection():
    """Создает соединение с базой данных"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def index():
    return render_template('index1.html')


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"})

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"})

    # Считываем файл и кодируем в base64
    file_content = file.read()
    base64_image = base64.b64encode(file_content).decode('utf-8')
    data_url = f"data:{file.mimetype};base64,{base64_image}"

    # Получаем текст запроса или используем значение по умолчанию
    prompt_text = request.form.get('message',
                                   "Опиши подробно, что ты видишь на этом изображении, объясни смысл мема и его происхождение.")

    # Создаем мультимодальный запрос к Pixtral
    try:
        chat_response = client.chat.complete(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt_text},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]
                },
            ]
        )
        analysis = chat_response.choices[0].message.content

        return jsonify({
            "message": "Image processed successfully",
            "analysis": analysis
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "No message provided"}), 400

    user_input = data['message']
    image_data = data.get('image')

    # Подготовка содержимого сообщения
    content = []

    # Добавляем текстовое сообщение
    content.append({"type": "text", "text": user_input})

    # Если изображение предоставлено, добавляем его
    if image_data:
        content.append({"type": "image_url", "image_url": {"url": image_data}})

    # Отправляем запрос с текстом и (опционально) изображением
    try:
        chat_response = client.chat.complete(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": content
                },
            ]
        )

        response_text = chat_response.choices[0].message.content
        return jsonify({"response": response_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/top-memes')
def top_memes():
    """Страница с популярными мемами"""
    conn = get_db_connection()

    # Получаем топ по лайкам
    cursor = conn.execute("""
        SELECT m.*, GROUP_CONCAT(t.tag) as tags
        FROM memes m
        LEFT JOIN tags t ON m.id = t.meme_id
        GROUP BY m.id
        ORDER BY m.likes DESC
        LIMIT 20
    """)
    top_by_likes = cursor.fetchall()

    # Получаем популярные теги
    cursor = conn.execute("""
        SELECT tag, COUNT(*) as count
        FROM tags
        GROUP BY tag
        ORDER BY count DESC
        LIMIT 15
    """)
    popular_tags = cursor.fetchall()

    # Подготавливаем данные для шаблона
    top_memes_list = []
    for meme in top_by_likes:
        meme_dict = dict(meme)
        # Форматируем дату
        if 'post_date' in meme_dict and meme_dict['post_date']:
            meme_dict['post_date_formatted'] = format_date(meme_dict['post_date'])
        else:
            meme_dict['post_date_formatted'] = "Неизвестно"

        # Разбиваем теги
        if meme_dict['tags']:
            meme_dict['tags'] = meme_dict['tags'].split(',')
        else:
            meme_dict['tags'] = []

        top_memes_list.append(meme_dict)

    conn.close()

    return render_template('top_memes.html',
                           top_memes=top_memes_list,
                           trending_memes=top_memes_list[:10],  # Используем топ по лайкам как тренды
                           popular_tags=popular_tags)


@app.route('/filter-memes')
def filter_memes():
    """Страница с фильтрацией мемов"""
    # Получаем параметры фильтрации из URL
    source = request.args.get('source', '')
    tag = request.args.get('tag', '')
    sort_by = request.args.get('sort_by', 'likes')
    order = request.args.get('order', 'desc')

    # Подключаемся к БД
    conn = get_db_connection()

    # Формируем SQL-запрос с учетом фильтров
    query = """
        SELECT m.*, GROUP_CONCAT(t.tag) as tags
        FROM memes m
        LEFT JOIN tags t ON m.id = t.meme_id
    """

    conditions = []
    params = []

    if source:
        conditions.append("m.source_platform = ?")
        params.append(source)

    if tag:
        conditions.append("EXISTS (SELECT 1 FROM tags WHERE meme_id = m.id AND tag = ?)")
        params.append(tag)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " GROUP BY m.id "

    # Добавляем сортировку
    valid_sort_columns = ['likes', 'views', 'comments', 'shares', 'post_date']
    if sort_by in valid_sort_columns:
        direction = "DESC" if order == 'desc' else "ASC"
        query += f" ORDER BY m.{sort_by} {direction}"
    else:
        query += " ORDER BY m.likes DESC"  # По умолчанию

    query += " LIMIT 50"

    # Выполняем запрос
    cursor = conn.execute(query, params)
    memes_data = cursor.fetchall()

    # Подготавливаем данные для шаблона
    memes_list = []
    for meme in memes_data:
        meme_dict = dict(meme)
        # Форматируем дату
        if 'post_date' in meme_dict and meme_dict['post_date']:
            meme_dict['post_date_formatted'] = format_date(meme_dict['post_date'])
        else:
            meme_dict['post_date_formatted'] = "Неизвестно"

        # Разбиваем теги
        if meme_dict['tags']:
            meme_dict['tags'] = meme_dict['tags'].split(',')
        else:
            meme_dict['tags'] = []

        memes_list.append(meme_dict)

    # Получаем все источники для фильтра
    cursor = conn.execute("SELECT DISTINCT source_platform FROM memes")
    sources = [row[0] for row in cursor.fetchall() if row[0]]

    # Получаем все теги
    cursor = conn.execute("SELECT DISTINCT tag FROM tags")
    tags = [row[0] for row in cursor.fetchall() if row[0]]

    conn.close()

    return render_template('filter_memes.html',
                           memes=memes_list,
                           sources=sources,
                           tags=tags,
                           current_source=source,
                           current_tag=tag,
                           current_sort=sort_by,
                           current_order=order)


if __name__ == '__main__':
    # Создаем директории если нужно
    os.makedirs('static/memes', exist_ok=True)

    app.run(debug=True)
