import aiosqlite
import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from sklearn.preprocessing import MinMaxScaler
import os
import logging


class MemeAnalyzer:
    def __init__(self, db_path: str, output_dir: str = 'analysis_results'):
        self.db_path = db_path
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        logging.basicConfig(level=logging.INFO)

    async def get_meme_data(self):
        """Извлекает данные о мемах из базы данных"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # Получаем основные данные о мемах
            query = """
            SELECT m.id, m.image_url, m.local_path, m.source_url, 
                   m.source_platform, m.post_date, m.collection_date, 
                   m.likes, m.views, m.comments, m.shares, m.text_content 
            FROM memes m
            """
            cursor = await db.execute(query)
            rows = await cursor.fetchall()

            # Создаем DataFrame
            memes_df = pd.DataFrame([dict(row) for row in rows])

            # Если DataFrame пустой, возвращаем его
            if memes_df.empty:
                return memes_df

            # Преобразуем строковые даты в datetime
            for date_col in ['post_date', 'collection_date']:
                if date_col in memes_df.columns:
                    memes_df[date_col] = pd.to_datetime(memes_df[date_col])

            # Получаем теги для каждого мема
            tags_dict = {}
            query = "SELECT meme_id, tag FROM tags"
            cursor = await db.execute(query)
            tag_rows = await cursor.fetchall()

            for row in tag_rows:
                meme_id = row['meme_id']
                tag = row['tag']
                if meme_id in tags_dict:
                    tags_dict[meme_id].append(tag)
                else:
                    tags_dict[meme_id] = [tag]

            # Добавляем теги в DataFrame
            memes_df['tags'] = memes_df['id'].map(lambda x: tags_dict.get(x, []))

            return memes_df

    async def analyze_memes(self, trend_window_days=15):
        """Анализирует мемы и распределяет их по метрикам"""
        df = await self.get_meme_data()

        if df.empty:
            logging.warning("База данных не содержит мемов для анализа")
            return None

        # Заполняем NA значения нулями для числовых колонок
        numeric_cols = ['likes', 'views', 'comments', 'shares']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].fillna(0)

        # Сортировка по лайкам и просмотрам
        by_likes = df.sort_values('likes', ascending=False)
        by_views = df.sort_values('views', ascending=False)

        # Вычисляем вирусность (отношение лайков к просмотрам)
        df['virality'] = df['likes'] / df['views'].apply(lambda x: max(x, 1))

        # Анализ трендов: рост популярности за последние дни
        now = datetime.now()
        trend_start = now - timedelta(days=trend_window_days)
        recent_df = df[df['post_date'] >= trend_start].copy()

        if not recent_df.empty:
            # Вычисляем скорость набора лайков и просмотров
            recent_df['days_active'] = (now - recent_df['post_date']).dt.total_seconds() / (24 * 3600)
            recent_df['likes_velocity'] = recent_df['likes'] / recent_df['days_active'].apply(lambda x: max(x, 0.5))
            recent_df['views_velocity'] = recent_df['views'] / recent_df['days_active'].apply(lambda x: max(x, 0.5))

            # Находим тренды - мемы с высокой скоростью набора лайков/просмотров
            trending = recent_df.sort_values('likes_velocity', ascending=False)
        else:
            trending = pd.DataFrame()

        # Оценка актуальности по дате и показателям
        df['recency'] = (now - df['post_date']).dt.total_seconds() / (24 * 3600)
        df['recency_score'] = np.exp(-0.05 * df['recency'])  # Экспоненциальное затухание

        # Нормализуем показатели для расчета общего рейтинга
        scaler = MinMaxScaler()
        metrics = ['likes', 'views', 'virality', 'recency_score']

        for metric in metrics:
            if metric in df.columns and not df[metric].empty:
                # Проверяем, что есть хотя бы одно ненулевое значение
                if df[metric].sum() > 0:
                    df[f'{metric}_norm'] = scaler.fit_transform(df[[metric]])
                else:
                    df[f'{metric}_norm'] = 0

        # Вычисляем общий рейтинг (можно настроить веса)
        # Проверяем наличие необходимых колонок
        required_cols = ['likes_norm', 'views_norm', 'virality_norm', 'recency_score_norm']
        if all(col in df.columns for col in required_cols):
            df['total_score'] = (
                    df['likes_norm'] * 0.3 +
                    df['views_norm'] * 0.3 +
                    df['virality_norm'] * 0.2 +
                    df['recency_score_norm'] * 0.2
            )
        else:
            # Если каких-то колонок нет, используем доступные
            available_cols = [col for col in required_cols if col in df.columns]
            if available_cols:
                df['total_score'] = df[available_cols].mean(axis=1)
            else:
                df['total_score'] = 0

        # Итоговое распределение по общему рейтингу
        overall_best = df.sort_values('total_score', ascending=False)

        # Анализ по тегам (популярные теги)
        if 'tags' in df.columns:
            all_tags = []
            for tags_list in df['tags']:
                if isinstance(tags_list, list):
                    all_tags.extend(tags_list)

            tags_df = pd.DataFrame({'tag': all_tags})
            popular_tags = tags_df['tag'].value_counts().reset_index()
            popular_tags.columns = ['tag', 'count']
        else:
            popular_tags = pd.DataFrame()

        return {
            'by_likes': by_likes,
            'by_views': by_views,
            'trending': trending,
            'overall_best': overall_best,
            'popular_tags': popular_tags
        }

    async def visualize_results(self, results, top_n=15):
        """Визуализирует результаты анализа"""
        if not results:
            logging.warning("Нет данных для визуализации")
            return

        # Топ мемов по лайкам
        if not results['by_likes'].empty:
            top_likes = results['by_likes'].head(top_n)
            plt.figure(figsize=(12, 6))
            plt.bar(top_likes['id'].astype(str), top_likes['likes'])
            plt.title('Топ мемов по лайкам')
            plt.xlabel('ID мема')
            plt.ylabel('Количество лайков')
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(f'{self.output_dir}/top_by_likes.png')
            plt.close()

        # Топ мемов по просмотрам
        if not results['by_views'].empty:
            top_views = results['by_views'].head(top_n)
            plt.figure(figsize=(12, 6))
            plt.bar(top_views['id'].astype(str), top_views['views'])
            plt.title('Топ мемов по просмотрам')
            plt.xlabel('ID мема')
            plt.ylabel('Количество просмотров')
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(f'{self.output_dir}/top_by_views.png')
            plt.close()

        # Топ трендовых мемов
        if 'trending' in results and not results['trending'].empty:
            top_trending = results['trending'].head(top_n)
            plt.figure(figsize=(12, 6))
            plt.bar(top_trending['id'].astype(str), top_trending['likes_velocity'])
            plt.title('Топ трендовых мемов (скорость набора лайков)')
            plt.xlabel('ID мема')
            plt.ylabel('Лайков в день')
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(f'{self.output_dir}/top_trending.png')
            plt.close()

        # Общий рейтинг
        if not results['overall_best'].empty:
            top_overall = results['overall_best'].head(top_n)
            plt.figure(figsize=(12, 6))
            plt.bar(top_overall['id'].astype(str), top_overall['total_score'])
            plt.title('Топ мемов по общему рейтингу')
            plt.xlabel('ID мема')
            plt.ylabel('Общий рейтинг')
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(f'{self.output_dir}/top_overall.png')
            plt.close()

        # Популярные теги
        if 'popular_tags' in results and not results['popular_tags'].empty:
            top_tags = results['popular_tags'].head(top_n)
            plt.figure(figsize=(12, 6))
            plt.bar(top_tags['tag'], top_tags['count'])
            plt.title('Самые популярные теги')
            plt.xlabel('Тег')
            plt.ylabel('Количество мемов')
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(f'{self.output_dir}/popular_tags.png')
            plt.close()

    async def create_html_report(self, results, top_n=15):
        """Создает HTML отчет с результатами анализа"""
        if not results:
            return

        # Функция для получения правильного пути к изображению
        def get_image_html(row):
            local_path = row.get('local_path', '')
            meme_id = row['id']

            if local_path and os.path.exists(local_path):
                # Используем относительный путь от директории отчета
                rel_path = os.path.relpath(local_path, self.output_dir)
                return f'<img src="{rel_path}" alt="Мем ID {meme_id}">'
            elif local_path and local_path.startswith(('http://', 'https://')):
                # Если это URL, используем его напрямую
                return f'<img src="{local_path}" alt="Мем ID {meme_id}">'
            else:
                # Если изображение не найдено
                return f'<div class="missing-image">Мем ID {meme_id}</div>'

        html = """
        <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>Анализ мемов</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            h1, h2 { color: #333; }
            table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            img { max-width: 100px; height: auto; }
            .section { margin-bottom: 30px; }
            .missing-image { background-color: #f0f0f0; width: 100px; height: 100px; 
                             display: flex; align-items: center; justify-content: center; 
                             text-align: center; font-size: 12px; color: #666; }
        </style>
    </head>
    <body>
        <h1>Анализ мемов</h1>
        """

        # 1. Добавляем раздел по лайкам
        if not results['by_likes'].empty:
            top_likes = results['by_likes'].head(top_n)
            html += """
            <div class="section">
                <h2>Топ мемов по лайкам</h2>
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Изображение</th>
                        <th>Платформа</th>
                        <th>Дата</th>
                        <th>Лайки</th>
                        <th>Просмотры</th>
                        <th>Теги</th>
                    </tr>
            """

            for _, row in top_likes.iterrows():
                tags_str = ", ".join(row['tags']) if isinstance(row.get('tags'), list) else ""
                post_date = row.get('post_date', '').strftime('%Y-%m-%d') if pd.notna(row.get('post_date')) else ""

                html += f"""
                <tr>
                    <td>{row['id']}</td>
                    <td>{get_image_html(row)}</td>
                    <td>{row.get('source_platform', '')}</td>
                    <td>{post_date}</td>
                    <td>{row.get('likes', 0)}</td>
                    <td>{row.get('views', 0)}</td>
                    <td>{tags_str}</td>
                </tr>
                """

            html += """
                </table>
            </div>
            """

        # 2. Добавляем раздел по просмотрам
        if not results['by_views'].empty:
            top_views = results['by_views'].head(top_n)
            html += """
            <div class="section">
                <h2>Топ мемов по просмотрам</h2>
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Изображение</th>
                        <th>Платформа</th>
                        <th>Дата</th>
                        <th>Просмотры</th>
                        <th>Лайки</th>
                        <th>Теги</th>
                    </tr>
            """

            for _, row in top_views.iterrows():
                tags_str = ", ".join(row['tags']) if isinstance(row.get('tags'), list) else ""
                post_date = row.get('post_date', '').strftime('%Y-%m-%d') if pd.notna(row.get('post_date')) else ""

                html += f"""
                <tr>
                    <td>{row['id']}</td>
                    <td>{get_image_html(row)}</td>
                    <td>{row.get('source_platform', '')}</td>
                    <td>{post_date}</td>
                    <td>{row.get('views', 0)}</td>
                    <td>{row.get('likes', 0)}</td>
                    <td>{tags_str}</td>
                </tr>
                """

            html += """
                </table>
            </div>
            """

        # 3. Добавляем раздел по трендам
        if 'trending' in results and not results['trending'].empty:
            top_trending = results['trending'].head(top_n)
            html += """
            <div class="section">
                <h2>Тренды (быстрорастущие мемы)</h2>
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Изображение</th>
                        <th>Платформа</th>
                        <th>Дата</th>
                        <th>Лайки/день</th>
                        <th>Всего лайков</th>
                        <th>Теги</th>
                    </tr>
            """

            for _, row in top_trending.iterrows():
                tags_str = ", ".join(row['tags']) if isinstance(row.get('tags'), list) else ""
                post_date = row.get('post_date', '').strftime('%Y-%m-%d') if pd.notna(row.get('post_date')) else ""

                html += f"""
                <tr>
                    <td>{row['id']}</td>
                    <td>{get_image_html(row)}</td>
                    <td>{row.get('source_platform', '')}</td>
                    <td>{post_date}</td>
                    <td>{row.get('likes_velocity', 0):.2f}</td>
                    <td>{row.get('likes', 0)}</td>
                    <td>{tags_str}</td>
                </tr>
                """

            html += """
                </table>
            </div>
            """

        # 4. Добавляем раздел по общему рейтингу
        if not results['overall_best'].empty:
            top_overall = results['overall_best'].head(top_n)
            html += """
            <div class="section">
                <h2>Лучшие мемы по общему рейтингу</h2>
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Изображение</th>
                        <th>Платформа</th>
                        <th>Дата</th>
                        <th>Рейтинг</th>
                        <th>Лайки</th>
                        <th>Просмотры</th>
                        <th>Теги</th>
                    </tr>
            """

            for _, row in top_overall.iterrows():
                tags_str = ", ".join(row['tags']) if isinstance(row.get('tags'), list) else ""
                post_date = row.get('post_date', '').strftime('%Y-%m-%d') if pd.notna(row.get('post_date')) else ""

                html += f"""
                <tr>
                    <td>{row['id']}</td>
                    <td>{get_image_html(row)}</td>
                    <td>{row.get('source_platform', '')}</td>
                    <td>{post_date}</td>
                    <td>{row.get('total_score', 0):.3f}</td>
                    <td>{row.get('likes', 0)}</td>
                    <td>{row.get('views', 0)}</td>
                    <td>{tags_str}</td>
                </tr>
                """

            html += """
                </table>
            </div>
            """

        # 5. Добавляем раздел с популярными тегами
        if 'popular_tags' in results and not results['popular_tags'].empty:
            top_tags = results['popular_tags'].head(top_n)
            html += """
            <div class="section">
                <h2>Популярные теги</h2>
                <table>
                    <tr>
                        <th>Тег</th>
                        <th>Количество мемов</th>
                    </tr>
            """

            for _, row in top_tags.iterrows():
                html += f"""
                <tr>
                    <td>{row['tag']}</td>
                    <td>{row['count']}</td>
                </tr>
                """

            html += """
                </table>
            </div>
            """

        # Закрываем HTML документ
        html += """
    </body>
    </html>
        """

        # Сохраняем отчет в файл
        report_path = f'{self.output_dir}/meme_analysis_report.html'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)

        logging.info(f"HTML отчет сохранен в {report_path}")
        return report_path

    async def run_analysis(self, trend_window_days=7, top_n=10):
        """Запускает полный анализ и создает отчет"""
        logging.info("Начало анализа мемов...")
        results = await self.analyze_memes(trend_window_days)

        if results:
            logging.info("Создание визуализаций...")
            await self.visualize_results(results, top_n)

            logging.info("Создание HTML отчета...")
            report_path = await self.create_html_report(results, top_n)

            logging.info(f"Анализ завершен. Отчет доступен по пути: {report_path}")
            return report_path
        else:
            logging.warning("Анализ не выполнен из-за отсутствия данных")
            return None

    # Пример использования


async def main():
    analyzer = MemeAnalyzer(db_path="memes.db")
    await analyzer.run_analysis()


if __name__ == "__main__":
    asyncio.run(main())
