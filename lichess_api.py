"""
Модуль для работы с API lichess.org для получения шахматных задач.
"""
import requests
from typing import Optional, Dict, Any
from io import BytesIO
import chess
import chess.pgn


class LichessAPI:
    """Класс для взаимодействия с API lichess.org."""
    
    BASE_URL = "https://lichess.org"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Telegram Chess Puzzle Bot'
        })
    
    def get_daily_puzzle(self) -> Optional[Dict[str, Any]]:
        """
        Получает задачу дня с lichess.org.
        
        Returns:
            Словарь с данными задачи или None в случае ошибки.
        """
        try:
            url = f"{self.BASE_URL}/api/puzzle/daily"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # ID задачи находится внутри объекта puzzle
            puzzle = data.get('puzzle', {})
            puzzle_id = puzzle.get('id') or data.get('id')
            
            # Рейтинг и количество попыток также могут быть в puzzle
            rating = puzzle.get('rating') or data.get('rating')
            plays = puzzle.get('plays') or data.get('plays')
            
            puzzle_data = {
                'id': puzzle_id,
                'rating': rating,
                'plays': plays,
                'puzzle': puzzle,
                'game': data.get('game'),
                'url': f"{self.BASE_URL}/training/{puzzle_id}" if puzzle_id else None
            }
            
            return puzzle_data
        except Exception as e:
            # Используем print, так как logger может быть не инициализирован
            print(f"Ошибка при получении задачи: {e}")
            return None
    
    def get_puzzle_by_id(self, puzzle_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает задачу по ID.
        
        Args:
            puzzle_id: ID задачи на lichess.org
            
        Returns:
            Словарь с данными задачи или None в случае ошибки.
        """
        try:
            url = f"{self.BASE_URL}/api/puzzle/{puzzle_id}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            puzzle_data = {
                'id': data.get('id'),
                'rating': data.get('rating'),
                'plays': data.get('plays'),
                'puzzle': data.get('puzzle'),
                'game': data.get('game'),
                'url': f"{self.BASE_URL}/training/{data.get('id')}"
            }
            
            return puzzle_data
        except Exception as e:
            # Используем print, так как logger может быть не инициализирован
            print(f"Ошибка при получении задачи по ID: {e}")
            return None
    
    def generate_board_image(self, fen: str) -> Optional[BytesIO]:
        """
        Генерирует изображение доски из FEN позиции используя внешний API.
        Доска отображается с координатами (цифры и буквы по краям).
        
        Args:
            fen: FEN строка позиции
            
        Returns:
            BytesIO объект с PNG изображением или None в случае ошибки.
        """
        # Используем backscattering.de API с координатами
        return self._generate_via_fen_to_image_api(fen)
    
    def _generate_via_fen_to_image_api(self, fen: str) -> Optional[BytesIO]:
        """Генерация через backscattering.de API с координатами."""
        try:
            # backscattering.de использует формат: пробелы заменяются на подчеркивания,
            # слэши остаются как есть, кодируются только специальные символы
            from urllib.parse import quote
            # Заменяем пробелы на подчеркивания
            fen_for_url = fen.replace(' ', '_')
            # Кодируем, но оставляем слэши и подчеркивания без изменений
            fen_encoded = quote(fen_for_url, safe='_/')
            # Добавляем параметр coordinates=1 для отображения координат
            url = f"https://backscattering.de/web-boardimage/board.png?fen={fen_encoded}&coordinates=1"
            
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            # Проверяем content-type
            content_type = response.headers.get('content-type', '').lower()
            if 'image' in content_type or len(response.content) > 1000:
                return BytesIO(response.content)
            else:
                # Пробуем альтернативные форматы
                return self._try_alternative_fen_format(fen)
        except Exception as e:
            print(f"Ошибка при генерации через backscattering: {e}")
            return self._try_alternative_fen_format(fen)
    
    def _try_alternative_fen_format(self, fen: str) -> Optional[BytesIO]:
        """Пробует альтернативные форматы FEN для API с координатами."""
        # Пробуем backscattering с разными форматами
        formats_to_try = [
            fen.replace(' ', '_'),  # Просто замена пробелов
            fen.replace(' ', '+'),   # Замена пробелов на плюсы
            ' '.join(fen.split()[:4]),  # Только первые 4 части FEN
        ]
        
        for fen_format in formats_to_try:
            try:
                from urllib.parse import quote
                fen_encoded = quote(fen_format, safe='_/')
                # Всегда добавляем coordinates=1 для координат
                url = f"https://backscattering.de/web-boardimage/board.png?fen={fen_encoded}&coordinates=1"
                
                response = self.session.get(url, timeout=15)
                if response.status_code == 200 and len(response.content) > 1000:
                    return BytesIO(response.content)
            except:
                continue
        
        return None
    
    def get_fen_from_puzzle(self, puzzle_data: Dict[str, Any]) -> str:
        """
        Извлекает FEN позицию из данных задачи.
        Возвращает позицию после первого хода решения (как она отображается на lichess.org).
        
        Args:
            puzzle_data: Данные задачи от API
            
        Returns:
            FEN строка позиции.
        """
        puzzle = puzzle_data.get('puzzle', {})
        game = puzzle_data.get('game', {})
        solution = puzzle.get('solution', [])
        
        # Пытаемся получить FEN из PGN
        pgn = game.get('pgn', '')
        if pgn:
            try:
                from io import StringIO
                pgn_io = StringIO(pgn)
                game_obj = chess.pgn.read_game(pgn_io)
                if game_obj:
                    board = game_obj.board()
                    # initialPly - это номер полухода, после которого начинается задача
                    # На lichess.org позиция показывается ДО первого хода решения
                    # Нужно сделать initialPly + 1 ходов из партии, чтобы получить позицию перед решением
                    initial_ply = puzzle.get('initialPly', 0)
                    move_count = 0
                    # Делаем initialPly + 1 ходов из партии (позиция перед решением)
                    for move in game_obj.mainline_moves():
                        if move_count >= initial_ply + 1:
                            break
                        board.push(move)
                        move_count += 1
                    
                    # НЕ делаем первый ход решения - показываем позицию, в которой нужно найти ход
                    return board.fen()
            except Exception as e:
                # Используем print, так как logger может быть не инициализирован
                print(f"Ошибка при парсинге PGN: {e}")
                import traceback
                traceback.print_exc()
        
        # Если не удалось получить из PGN, возвращаем начальную позицию
        return chess.Board().fen()
    
    def download_board_image(self, fen: str) -> Optional[BytesIO]:
        """
        Генерирует или загружает изображение доски.
        
        Args:
            fen: FEN строка позиции
            
        Returns:
            BytesIO объект с изображением или None в случае ошибки.
        """
        # Пробуем сгенерировать локально
        image = self.generate_board_image(fen)
        if image:
            return image
        
        # Если не получилось, возвращаем None
        return None
    
    def format_puzzle_description(self, puzzle_data: Dict[str, Any], fen: str, include_solution: bool = False) -> str:
        """
        Форматирует описание задачи для отправки в Telegram.
        
        Args:
            puzzle_data: Данные задачи
            fen: FEN позиция доски
            include_solution: Включить решение под спойлером
            
        Returns:
            Отформатированное описание задачи.
        """
        puzzle = puzzle_data.get('puzzle', {})
        rating = puzzle_data.get('rating')
        plays = puzzle_data.get('plays')
        themes = puzzle.get('themes', [])
        
        # Определяем, чей ход
        board = chess.Board(fen)
        turn_text = "Ход белых" if board.turn == chess.WHITE else "Ход черных"
        
        # Определяем требование задачи из themes
        requirement = "Найти лучший ход"
        if themes:
            theme_translations = {
                'mate': 'Поставить мат',
                'mateIn1': 'Мат в 1 ход',
                'mateIn2': 'Мат в 2 хода',
                'mateIn3': 'Мат в 3 хода',
                'endgame': 'Эндшпиль',
                'advantage': 'Получить преимущество',
                'crushing': 'Решающее преимущество',
                'defensive': 'Защита',
                'attacking': 'Атака',
                'tactics': 'Тактика',
                'middlegame': 'Миттельшпиль',
                'opening': 'Дебют',
                'short': 'Короткая задача',
                'long': 'Длинная задача'
            }
            
            # Ищем наиболее подходящее требование
            for theme in themes:
                if theme in theme_translations:
                    requirement = theme_translations[theme]
                    break
            
            # Если есть несколько тем, формируем более подробное описание
            if len(themes) > 1:
                main_themes = [theme_translations.get(t, t) for t in themes[:3] if t in theme_translations]
                if main_themes:
                    requirement = ', '.join(main_themes)
        
        description = f"🎯 <b>Шахматная задача дня</b>\n\n"
        
        # Добавляем рейтинг и попытки только если они есть
        if rating is not None:
            description += f"📊 Рейтинг: {rating}\n"
        if plays is not None:
            description += f"👥 Попыток: {plays}\n"
        
        if rating is not None or plays is not None:
            description += "\n"
        
        description += f"⚪⚫ {turn_text}\n"
        description += f"🎯 Задача: {requirement}\n"
        
        # Добавляем ссылку только если URL валидный
        puzzle_url = puzzle_data.get('url')
        if puzzle_url and puzzle_url != f"{self.BASE_URL}/training/None":
            description += f"\n🔗 <a href=\"{puzzle_url}\">Открыть на lichess.org</a>"
        elif puzzle_data.get('id'):
            # Если URL не сформирован, но есть ID, формируем его заново
            puzzle_id = puzzle_data.get('id')
            description += f"\n🔗 <a href=\"{self.BASE_URL}/training/{puzzle_id}\">Открыть на lichess.org</a>"
        
        # Добавляем решение под спойлером, если нужно
        # Используем маркер для разделения в bot.py
        if include_solution:
            solution_text = self.format_solution(puzzle_data)
            description += f"\n\n━━━━━━━━━━━━━━━━\n"
            description += f"💡 <b>Решение (нажмите, чтобы раскрыть):</b>\n"
            description += f"<tg-spoiler>{solution_text}</tg-spoiler>"
        
        return description
    
    def format_solution(self, puzzle_data: Dict[str, Any]) -> str:
        """
        Форматирует решение задачи.
        
        Args:
            puzzle_data: Данные задачи
            
        Returns:
            Отформатированное решение.
        """
        puzzle = puzzle_data.get('puzzle', {})
        moves = puzzle.get('solution', [])
        
        if not moves:
            return "Решение недоступно."
        
        solution_text = "✅ <b>Решение:</b>\n\n"
        
        # Получаем FEN для конвертации UCI ходов в шахматную нотацию
        # ВАЖНО: используем тот же FEN, что и для отображения доски
        fen = self.get_fen_from_puzzle(puzzle_data)
        board = chess.Board(fen)
        
        # Форматируем ходы, конвертируя UCI в шахматную нотацию
        move_list = []
        temp_board = board.copy()
        
        for i, uci_move in enumerate(moves):
            try:
                move = chess.Move.from_uci(uci_move)
                if move in temp_board.legal_moves:
                    san_move = temp_board.san(move)
                    temp_board.push(move)
                    
                    # Группируем ходы белых и черных
                    if i % 2 == 0:
                        move_num = (i // 2) + 1
                        if i + 1 < len(moves):
                            # Есть ответ черных
                            next_uci = moves[i + 1]
                            try:
                                next_move = chess.Move.from_uci(next_uci)
                                if next_move in temp_board.legal_moves:
                                    next_san = temp_board.san(next_move)
                                    move_list.append(f"{move_num}. {san_move} {next_san}")
                                else:
                                    move_list.append(f"{move_num}. {san_move}")
                            except:
                                move_list.append(f"{move_num}. {san_move}")
                        else:
                            move_list.append(f"{move_num}. {san_move}")
            except Exception:
                # Если не удалось конвертировать, используем UCI
                if i % 2 == 0:
                    move_num = (i // 2) + 1
                    move_list.append(f"{move_num}. {uci_move}")
                else:
                    move_list[-1] += f" {uci_move}"
        
        if not move_list:
            # Fallback: просто показываем UCI ходы
            for i in range(0, len(moves), 2):
                white_move = moves[i] if i < len(moves) else ""
                black_move = moves[i + 1] if i + 1 < len(moves) else ""
                move_num = (i // 2) + 1
                if black_move:
                    move_list.append(f"{move_num}. {white_move} {black_move}")
                else:
                    move_list.append(f"{move_num}. {white_move}")
        
        solution_text += "\n".join(move_list)
        
        return solution_text

