# meme_parser.py
import asyncio
import aiohttp
import sqlite3
from datetime import datetime
import hashlib
import os
import logging
from bs4 import BeautifulSoup
import random
import time
import re

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


class MemeParser:
    def __init__(self, db_path, download_path='static/memes'):
        self.db_path = db_path
        self.download_path = download_path
        os.makedirs(download_path, exist_ok=True)

        # Инициализация базы данных, если она не существует
        self._init_db()

    def _init_db(self):
        """Инициализация базы данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Создаем таблицу memes если не существует
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS memes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_url TEXT UNIQUE,
            local_path TEXT,
            source_url TEXT,
            source_platform TEXT,
            post_date TIMESTAMP,
            collection_date TIMESTAMP,
            likes INTEGER,
            views INTEGER,
            comments INTEGER,
            shares INTEGER,
            text_content TEXT,
            image_hash TEXT
        )
        ''')

        # Создаем таблицу tags если не существует
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meme_id INTEGER,
            tag TEXT,
            FOREIGN KEY(meme_id) REFERENCES memes(id),
            UNIQUE(meme_id, tag)
        )
        ''')

        conn.commit()
        conn.close()

    async def download_image(self, session, url, filename):
        """Скачивает изображение по URL"""
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.read()
                    with open(filename, 'wb') as f:
                        f.write(data)
                    return filename
        except Exception as e:
            logging.error(f"Ошибка при скачивании изображения {url}: {e}")
        return None

    def calculate_image_hash(self, filename):
        """Вычисляет хеш изображения для проверки дубликатов"""
        if os.path.exists(filename):
            with open(filename, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        return None

    async def save_meme_to_db(self, meme_data):
        """Сохраняет информацию о меме в базу данных"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Проверяем существование мема по image_url
            cursor.execute("SELECT id FROM memes WHERE image_url = ?",
                           (meme_data['image_url'],))
            existing = cursor.fetchone()

            if existing:
                # Обновляем существующий мем
                meme_id = existing[0]
                cursor.execute('''
                UPDATE memes SET 
                    likes = ?, views = ?, comments = ?, shares = ?,
                    collection_date = ?
                WHERE id = ?
                ''', (
                    meme_data['likes'], meme_data['views'],
                    meme_data['comments'], meme_data['shares'],
                    datetime.now(), meme_id
                ))
            else:
                # Добавляем новый мем
                cursor.execute('''
                INSERT INTO memes (
                    image_url, local_path, source_url, source_platform,
                    post_date, collection_date, likes, views, 
                    comments, shares, text_content, image_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    meme_data['image_url'], meme_data['local_path'],
                    meme_data['source_url'], meme_data['source_platform'],
                    meme_data['post_date'], datetime.now(),
                    meme_data['likes'], meme_data['views'],
                    meme_data['comments'], meme_data['shares'],
                    meme_data['text_content'], meme_data['image_hash']
                ))

                meme_id = cursor.lastrowid

                # Добавляем теги
                for tag in meme_data['tags']:
                    cursor.execute('''
                    INSERT OR IGNORE INTO tags (meme_id, tag)
                    VALUES (?, ?)
                    ''', (meme_id, tag))

            conn.commit()
            return True

        except Exception as e:
            logging.error(f"Ошибка при сохранении мема в БД: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    async def parse_vk_memes(self, public_ids=['jumoreski', 'sciencemem', 'memasy']):
        """Парсит мемы из пабликов ВКонтакте"""
        logging.info(f"Начинаем парсинг мемов из ВКонтакте: {public_ids}")

        # Примечание: для реального парсинга нужно использовать VK API с токеном
        # Это упрощенная имитация для примера

        async with aiohttp.ClientSession() as session:
            for public_id in public_ids:
                logging.info(f"Парсинг паблика: {public_id}")

                # В реальном приложении здесь должен быть API запрос к VK API
                # Имитация данных для примера
                for i in range(5):  # Парсим по 5 мемов из каждого паблика
                    # Генерируем случайные данные для примера
                    likes = random.randint(100, 10000)
                    views = random.randint(likes, likes * 10)
                    image_url = f"https://example.com/vk/{public_id}/meme{i}.jpg"

                    # Скачивание изображения (в реальности)
                    # local_path = await self.download_image(session, image_url,
                    #    f"{self.download_path}/vk_{public_id}_{i}.jpg")

                    # Для примера используем заглушку
                    local_path = f"{self.download_path}/vk_{public_id}_{i}.jpg"

                    meme_data = {
                        'image_url': image_url,
                        'local_path': local_path,
                        'source_url': f"https://vk.com/{public_id}",
                        'source_platform': 'vk',
                        'post_date': datetime.now(),
                        'likes': likes,
                        'views': views,
                        'comments': random.randint(10, 1000),
                        'shares': random.randint(5, 500),
                        'text_content': f"Мем из паблика {public_id}",
                        'image_hash': f"hash_{public_id}_{i}",
                        'tags': [public_id, "мем", "юмор"]
                    }

                    await self.save_meme_to_db(meme_data)

                # Делаем паузу между запросами к разным пабликам
                await asyncio.sleep(1)

    async def parse_telegram_memes(self, channel_ids=['dvachannel', 'russiamemes']):
        """Парсит мемы из Telegram-каналов"""
        logging.info(f"Начинаем парсинг мемов из Telegram: {channel_ids}")

        # Примечание: для реального парсинга нужно использовать библиотеку telethon или pyrogram
        # с авторизацией. Это упрощенная имитация для примера

        async with aiohttp.ClientSession() as session:
            for channel_id in channel_ids:
                logging.info(f"Парсинг канала: {channel_id}")

                # Имитация данных для примера
                for i in range(3):  # Парсим по 3 мема из каждого канала
                    # Генерируем случайные данные
                    views = random.randint(1000, 50000)

                    meme_data = {
                        'image_url': f"https://example.com/telegram/{channel_id}/meme{i}.jpg",
                        'local_path': f"{self.download_path}/tg_{channel_id}_{i}.jpg",
                        'source_url': f"https://t.me/{channel_id}",
                        'source_platform': 'telegram',
                        'post_date': datetime.now(),
                        'likes': 0,  # Telegram не показывает лайки публично
                        'views': views,
                        'comments': 0,
                        'shares': 0,
                        'text_content': f"Мем из канала {channel_id}",
                        'image_hash': f"hash_tg_{channel_id}_{i}",
                        'tags': [channel_id, "мем", "телеграм"]
                    }

                    await self.save_meme_to_db(meme_data)

                await asyncio.sleep(1)

    async def run_parsers(self):
        """Запускает все парсеры"""
        logging.info("Запуск парсеров мемов")

        tasks = [
            self.parse_vk_memes(),
            self.parse_telegram_memes(),
            # Можно добавить другие парсеры
        ]

        await asyncio.gather(*tasks)
        logging.info("Парсинг мемов завершен")


# Пример использования
if __name__ == "__main__":
    parser = MemeParser("memes1.db")
    asyncio.run(parser.run_parsers())