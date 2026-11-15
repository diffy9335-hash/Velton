"""VELTON: the small, deliberately data-driven career decision engine."""
from __future__ import annotations
import random

ROLES = {
    "player": {"name": "Футболист", "short": "ИГ", "subtitle": "От дебюта до футбольной легенды", "name_label": "Имя игрока", "place_label": "Первый клуб", "default_place": "ФК Север", "metrics": {"skill": 54, "form": 74, "reputation": 18, "goals": 0, "appearances": 0}, "stats": [("skill", "Мастерство"), ("form", "Форма"), ("reputation", "Репутация"), ("goals", "Голы")]},
    "coach": {"name": "Тренер", "short": "ТР", "subtitle": "Тактика, раздевалка, результаты", "name_label": "Имя тренера", "place_label": "Команда", "default_place": "ФК Север", "metrics": {"tactics": 53, "chemistry": 62, "trust": 48, "wins": 0, "matches": 0}, "stats": [("tactics", "Тактика"), ("chemistry", "Атмосфера"), ("trust", "Доверие"), ("wins", "Победы")]},
    "referee": {"name": "Судья", "short": "СУ", "subtitle": "Самые сложные решения на поле", "name_label": "Имя судьи", "place_label": "Регион", "default_place": "Северная лига", "metrics": {"accuracy": 62, "authority": 55, "fitness": 76, "correct": 0, "matches": 0}, "stats": [("accuracy", "Точность"), ("authority", "Авторитет"), ("fitness", "Форма"), ("correct", "Верные решения")]},
    "agent": {"name": "Агент", "short": "АГ", "subtitle": "Клиенты, контракты, переговоры", "name_label": "Имя агента", "place_label": "Название агентства", "default_place": "Velton Agency", "metrics": {"reputation": 36, "connections": 44, "clients": 2, "deals": 0, "capital": 18}, "stats": [("reputation", "Репутация"), ("connections", "Связи"), ("clients", "Клиенты"), ("deals", "Сделки")]},
    "club": {"name": "Свой клуб", "short": "КЛ", "subtitle": "Создай клуб и управляй им", "name_label": "Название клуба", "place_label": "Город", "default_place": "Североград", "metrics": {"academy": 43, "facilities": 38, "finances": 55, "fans": 32, "trophies": 0}, "stats": [("academy", "Академия"), ("facilities", "База"), ("finances", "Финансы"), ("fans", "Болельщики")]},
}

# Choice format: (title, description, success odds, favorable metric deltas, unfavorable metric deltas)
EVENTS = {
    "player": [
        {"title": "Первое место в основе", "text": "Тренер доверяет тебе важный матч. Как проявить себя?", "choices": [
            ("Играть смело", "Чаще обострять и идти в дриблинг", 62, {"skill": 3, "reputation": 4, "goals": 1, "form": -3}, {"form": -7, "reputation": -2}),
            ("Сыграть на команду", "Сохранить баланс и помочь партнёрам", 82, {"skill": 2, "reputation": 2, "form": 1}, {"reputation": -1}),
            ("Выйти на замену", "Набрать форму без лишнего риска", 92, {"form": 6, "skill": 1}, {"reputation": -2})]},
        {"title": "Тренировка перед дерби", "text": "До главной игры недели всего два дня. На чём сосредоточишься?", "choices": [
            ("Удар и техника", "Добавить остроты в атаке", 73, {"skill": 4, "form": -3}, {"form": -6}),
            ("Работа над физикой", "Прибавить выносливость", 84, {"form": 7, "skill": 1}, {"form": -2}),
            ("Восстановление", "Подойти к игре свежим", 95, {"form": 5}, {"reputation": -1})]},
        {"title": "Интерес другого клуба", "text": "Тебя заметили скауты. Агент предлагает обсудить переход.", "choices": [
            ("Принять вызов", "Пробиться на более высокий уровень", 57, {"reputation": 9, "skill": 3}, {"form": -5, "reputation": -4}),
            ("Остаться и прогрессировать", "Бороться за место в основе", 82, {"skill": 3, "form": 3}, {"reputation": -1}),
            ("Попросить время", "Не принимать поспешных решений", 92, {"form": 2, "reputation": 1}, {"reputation": -2})]},
        {"title": "Решающий стандарт", "text": "На последних минутах команда заработала штрафной. Ты у мяча.", "choices": [
            ("Бить напрямую", "Попытаться забить красивый гол", 49, {"goals": 1, "reputation": 8, "skill": 2}, {"reputation": -3}),
            ("Разыграть комбинацию", "Передать инициативу партнёрам", 77, {"reputation": 3, "skill": 2}, {"reputation": -1}),
            ("Доверить капитану", "Выбрать командный вариант", 91, {"form": 3, "reputation": 1}, {"reputation": -2})]},
    ],
    "coach": [
        {"title": "План на важный матч", "text": "Соперник играет высоким прессингом. Выбери стратегию.", "choices": [
            ("Агрессивная атака", "Постоянный прессинг и высокий риск", 56, {"wins": 1, "tactics": 5, "trust": 5, "chemistry": -3}, {"trust": -5, "chemistry": -4}),
            ("Контратаки", "Компактная оборона и быстрые выходы", 73, {"wins": 1, "tactics": 3, "trust": 3}, {"trust": -2}),
            ("Контроль мяча", "Спокойная позиционная игра", 83, {"chemistry": 4, "tactics": 2}, {"trust": -2})]},
        {"title": "Конфликт в раздевалке", "text": "Два лидера команды спорят о составе перед дерби.", "choices": [
            ("Жёсткая дисциплина", "Поставить интересы клуба выше имён", 65, {"trust": 5, "chemistry": 2}, {"chemistry": -7}),
            ("Открытый разговор", "Собрать игроков и найти компромисс", 83, {"chemistry": 6, "trust": 2}, {"trust": -2}),
            ("Передать капитану", "Дать коллективу решить конфликт", 74, {"chemistry": 4}, {"trust": -5})]},
        {"title": "Молодой талант", "text": "В академии растёт перспективный нападающий. Что делать?", "choices": [
            ("Сразу в старт", "Дать шанс в ответственном матче", 61, {"tactics": 3, "trust": 6, "wins": 1}, {"trust": -4}),
            ("Постепенно вводить", "Увеличивать время на поле", 86, {"tactics": 3, "chemistry": 3}, {"trust": -1}),
            ("Оставить в молодёжке", "Сохранить стабильный состав", 93, {"chemistry": 2}, {"trust": -3})]},
        {"title": "Плотный календарь", "text": "Три матча за неделю, лидеры устали.", "choices": [
            ("Ротация состава", "Довериться резервистам", 79, {"chemistry": 5, "tactics": 2}, {"trust": -3}),
            ("Выставить сильнейших", "Играть основой каждый раз", 60, {"wins": 1, "trust": 4, "chemistry": -4}, {"chemistry": -6}),
            ("Упростить схему", "Прагматичный футбол без риска", 87, {"tactics": 2, "trust": 2}, {"trust": -2})]},
    ],
    "referee": [
        {"title": "Спорный пенальти", "text": "Игрок падает в штрафной после контакта. Трибуны требуют свисток.", "choices": [
            ("Назначить пенальти", "Быстро оценить контакт", 58, {"accuracy": 5, "authority": 4, "correct": 1}, {"accuracy": -6, "authority": -4}),
            ("Продолжить игру", "Не поддаваться давлению", 65, {"accuracy": 4, "authority": 3, "correct": 1}, {"accuracy": -5}),
            ("Проверить повтор", "Использовать доступную видеопроверку", 91, {"accuracy": 5, "correct": 1}, {"authority": -2})]},
        {"title": "Массовая стычка", "text": "После жёсткого подката игроки обеих команд окружают тебя.", "choices": [
            ("Показать карточки", "Жёстко пресечь конфликт", 72, {"authority": 7, "accuracy": 2, "correct": 1}, {"authority": -4}),
            ("Успокоить капитанов", "Поговорить с лидерами", 84, {"authority": 4, "fitness": 1, "correct": 1}, {"authority": -2}),
            ("Дать устное предупреждение", "Не разжигать эмоции", 69, {"authority": 3}, {"accuracy": -4})]},
        {"title": "Момент вне игры", "text": "На последней минуте забит спорный гол. Лайнсмен не уверен.", "choices": [
            ("Зафиксировать офсайд", "Довериться первому впечатлению", 56, {"accuracy": 5, "correct": 1}, {"accuracy": -7}),
            ("Засчитать гол", "Решить эпизод без задержки", 54, {"accuracy": 5, "authority": 2, "correct": 1}, {"accuracy": -6}),
            ("Сверить с помощником", "Перепроверить положение игроков", 90, {"accuracy": 4, "correct": 1}, {"authority": -2})]},
        {"title": "Давление после матча", "text": "Тренер публично критикует твоё решение, пресса ждёт ответа.", "choices": [
            ("Дать разъяснение", "Спокойно объяснить применение правил", 84, {"authority": 5, "accuracy": 2}, {"authority": -2}),
            ("Не комментировать", "Соблюсти нейтральность", 91, {"authority": 2, "fitness": 2}, {"authority": -1}),
            ("Ответить резко", "Защитить репутацию публично", 46, {"authority": 8}, {"authority": -8, "fitness": -3})]},
    ],
    "agent": [
        {"title": "Трансфер перспективного игрока", "text": "Два клуба заинтересованы в твоём подопечном. Как вести переговоры?", "choices": [
            ("Максимальный контракт", "Сделать ставку на крупные условия", 52, {"deals": 1, "capital": 9, "reputation": 7}, {"reputation": -5, "connections": -3}),
            ("Разумный компромисс", "Предложить реалистичный проект", 82, {"deals": 1, "capital": 5, "connections": 3}, {"reputation": -1}),
            ("Отложить переход", "Подождать более выгодного окна", 90, {"reputation": 3, "connections": 2}, {"capital": -2})]},
        {"title": "Новый клиент", "text": "Молодой полузащитник ищет агента для старта карьеры.", "choices": [
            ("Подписать сразу", "Вложить время в перспективу", 72, {"clients": 1, "reputation": 3, "capital": -2}, {"capital": -4}),
            ("Проверить потенциал", "Посмотреть матчи и статистику", 86, {"clients": 1, "connections": 2}, {"capital": -2}),
            ("Отказаться", "Сосредоточиться на текущих клиентах", 95, {"capital": 3}, {"reputation": -2})]},
        {"title": "Конфликт интересов", "text": "Клуб предлагает бонус за сделку, невыгодную футболисту.", "choices": [
            ("Защитить интересы клиента", "Отказаться от сомнительных условий", 88, {"reputation": 7, "connections": 2}, {"capital": -4}),
            ("Искать другой клуб", "Предложить альтернативу", 75, {"deals": 1, "reputation": 5, "capital": 3}, {"connections": -3}),
            ("Принять предложение", "Выбрать быстрый заработок", 51, {"capital": 10, "deals": 1, "reputation": -6}, {"reputation": -10, "clients": -1})]},
        {"title": "Контракт заканчивается", "text": "Ключевой игрок через месяц станет свободным агентом.", "choices": [
            ("Продлить соглашение", "Договориться без смены команды", 83, {"deals": 1, "capital": 4, "reputation": 3}, {"connections": -2}),
            ("Найти новый чемпионат", "Расширить международные связи", 59, {"deals": 1, "connections": 7, "capital": 7}, {"reputation": -3}),
            ("Выждать предложения", "Изучить рынок", 91, {"connections": 3}, {"capital": -2})]},
    ],
    "club": [
        {"title": "Первая большая инвестиция", "text": "Бюджет ограничен. Какое направление выбрать для развития клуба?", "choices": [
            ("Улучшить академию", "Создать базу для будущих звёзд", 83, {"academy": 8, "finances": -5}, {"finances": -5}),
            ("Обновить стадион", "Повысить комфорт для болельщиков", 75, {"facilities": 7, "fans": 5, "finances": -6}, {"finances": -7}),
            ("Сохранить резерв", "Укрепить финансовую устойчивость", 94, {"finances": 7}, {"fans": -2})]},
        {"title": "Выбор спортивного директора", "text": "Тебе предлагают двух специалистов с разной философией работы.", "choices": [
            ("Ставка на молодёжь", "Развивать академию и скаутинг", 83, {"academy": 6, "finances": 2}, {"fans": -2}),
            ("Готовые звёзды", "Ускорить рост популярности", 58, {"fans": 9, "trophies": 1, "finances": -8}, {"finances": -9}),
            ("Опытный управленец", "Улучшить структуру клуба", 87, {"facilities": 4, "finances": 3}, {"finances": -2})]},
        {"title": "День болельщика", "text": "Фанаты просят сделать билеты доступнее и провести открытую встречу.", "choices": [
            ("Снизить цены", "Сделать футбол ближе к городу", 91, {"fans": 8, "finances": -3}, {"finances": -2}),
            ("Организовать фестиваль", "Провести большой клубный день", 79, {"fans": 7, "facilities": 2, "finances": -5}, {"finances": -6}),
            ("Сохранить цены", "Не рисковать доходами", 94, {"finances": 4}, {"fans": -4})]},
        {"title": "Новый сезон", "text": "Пора сформировать задачи клуба на ближайшие месяцы.", "choices": [
            ("Бороться за трофей", "Рискнуть ресурсами ради результата", 47, {"trophies": 1, "fans": 11, "finances": -7}, {"finances": -8, "fans": -5}),
            ("Укрепить основу", "Повысить стабильность клуба", 82, {"facilities": 5, "academy": 3}, {"finances": -3}),
            ("Развивать инфраструктуру", "Построить долгосрочную систему", 89, {"facilities": 8, "finances": -3}, {"finances": -4})]},
    ],
}

ACHIEVEMENTS = [
    {"id": "pioneer", "name": "Старт истории", "desc": "Создать первую карьеру", "kind": "СТ"},
    {"id": "first_move", "name": "Первый ход", "desc": "Принять первое решение", "kind": "01"},
    {"id": "five_moves", "name": "В игре", "desc": "Принять 5 решений", "kind": "05"},
    {"id": "twenty_moves", "name": "Ветеран", "desc": "Принять 20 решений", "kind": "20"},
    {"id": "two_paths", "name": "Два пути", "desc": "Попробовать 2 разные роли", "kind": "02"},
    {"id": "all_paths", "name": "Все стороны футбола", "desc": "Открыть все 5 ролей", "kind": "05"},
    {"id": "goalscorer", "name": "Бомбардир", "desc": "Забить 3 гола за игрока", "kind": "ГЛ"},
    {"id": "strategist", "name": "Тактик", "desc": "Одержать 3 победы за тренера", "kind": "ТР"},
    {"id": "fair_play", "name": "Арбитр", "desc": "Вынести 3 верных решения", "kind": "СУ"},
    {"id": "deal_maker", "name": "Переговорщик", "desc": "Провести 3 сделки", "kind": "АГ"},
    {"id": "club_legend", "name": "Трофейный кабинет", "desc": "Завоевать первый трофей клуба", "kind": "КЛ"},
    {"id": "first_season", "name": "Первый сезон", "desc": "Подвести итоги первого полного сезона", "kind": "S1"},
    {"id": "three_seasons", "name": "Настоящий профессионал", "desc": "Завершить 3 сезона", "kind": "S3"},
    {"id": "first_deal", "name": "Первый трансфер", "desc": "Провести сделку на трансферном рынке", "kind": "ТР"},
    {"id": "farewell", "name": "Конец эпохи", "desc": "Завершить карьеру и освободить слот", "kind": "ФН"},
]

def choose_event(role: str, turn: int, previous: int | None = None) -> int:
    count = len(EVENTS[role])
    if turn == 0:
        return 0
    possibilities = [i for i in range(count) if i != previous]
    return random.choice(possibilities)

def event_view(role: str, index: int) -> dict:
    item = EVENTS[role][index]
    return {"id": index, "title": item["title"], "text": item["text"], "choices": [{"id": i, "title": c[0], "detail": c[1], "risk": "Смелый" if c[2] < 65 else "Взвешенный" if c[2] < 85 else "Осторожный"} for i, c in enumerate(item["choices"])]}

def resolve(role: str, event_index: int, choice_index: int, metrics: dict) -> tuple[bool, dict, str]:
    event = EVENTS[role][event_index]
    choice = event["choices"][choice_index]
    # Influencing success is deliberately small; no paid randomness or hidden advantage.
    core = {"player":"skill", "coach":"tactics", "referee":"accuracy", "agent":"connections", "club":"finances"}[role]
    odds = max(15, min(95, choice[2] + round((metrics[core] - 50) * .13)))
    success = random.random() * 100 < odds
    delta = dict(choice[3] if success else choice[4])
    for key, amount in delta.items():
        old = metrics.get(key, 0)
        new = max(0, min(100, old + amount)) if key not in {"goals", "appearances", "wins", "matches", "correct", "clients", "deals", "trophies", "capital"} else max(0, old + amount)
        metrics[key] = new
        delta[key] = new - old
    if role == "player":
        metrics["appearances"] += 1
    elif role in ("coach", "referee"):
        metrics["matches"] += 1
    summary = ("План сработал. " if success else "На этот раз не всё получилось. ") + (
        "Следующая неделя уже впереди." if role in ("player", "coach") else
        "Твоё решение повлияло на репутацию и развитие." if role in ("referee", "agent") else
        "Клуб продолжает двигаться к своей цели.")
    return success, delta, summary
