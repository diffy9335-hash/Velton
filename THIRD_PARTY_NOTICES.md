# Уведомления о сторонних данных

## OpenFootball — CC0

Источники: https://github.com/openfootball/football.json, https://github.com/openfootball/europe, https://github.com/openfootball/world. Списки участников переписаны из свободных данных матчей под CC0 1.0 Universal: https://creativecommons.org/publicdomain/zero/1.0/ . Содержимое исходных матчей и результаты не используются в игровом движке. Годы источников сохранены у клубов.

## ericsanmiguel/football_elo — MIT

URL: https://github.com/ericsanmiguel/football_elo/tree/main/data/squads

Данные об отдельных именах и клубной принадлежности на старте ЧМ-2026, не современный официальный состав клуба. Лицензия MIT, Copyright (c) 2026 Eric San Miguel.

MIT License

Copyright (c) 2026 Eric San Miguel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Другие источники клубов

Реестры URU, CHI, KOR, RUS и SRB состоят из перечней названий из указанной публичной информации. Их URL записаны у каждой команды и в `world_data/coverage_manifest.json`. Их копии матчей, эмблемы и изображения в комплект не входят. Вопрос прав на официальную футбольную символику решается отдельно.

## VELTON v0.6: дополнительные источники участников

Имена клубов и их историческое присутствие в дивизионах сверены вручную по публичным страницам национальных федераций (USL, FFF, RFEF, SPFL, J.League, LNFP), Lega Pro (Италия), TFF (Турция), OpenFootball, RSSSF, Transfermarkt и другим документированным ссылкам, перечисленным в `world_data/verified_lower_leagues_audit_v06.json`. Из этих источников не воспроизводятся статистика матчей, копии страниц, фото, изображения, эмблемы или готовые лицензируемые базы игроков. При коммерческом использовании следует отдельно проверить права на бренд, символику и условия поставщиков данных.

## VELTON v0.7: matyuschenko/fifa-wc2026-players — CC BY 4.0

Источник: https://github.com/matyuschenko/fifa-wc2026-players/blob/main/data/players.tsv

Лицензия: Creative Commons Attribution 4.0 International — https://creativecommons.org/licenses/by/4.0/

Использована только ограниченная часть сведений из датированного снимка игроков сборных ЧМ-2026: имя, позиция и указанная в исходном снимке клубная принадлежность. Данные переработаны, написания унифицированы, пропущены уже существующие в VELTON игроки и неоднозначные совпадения клубов, поэтому этот пакет НЕ является полной копией исходного набора. Дата исходного снимка: 2026-09-10. Авторство принадлежит составителю указанного репозитория. Использование не подразумевает одобрения VELTON первоначальным автором. Матчи, рейтинги, стоимости и зарплаты в VELTON симулируются отдельно.

## Опциональные внешние CSV

Инструмент `tools/convert_roster_snapshot.py` может обработать локальный CSV других провайдеров, но такие файлы не поставляются с VELTON v0.7. Проверь лицензию и дату каждого источника отдельно.


## VELTON v0.8: публичные официальные заявки клубов 2026/27

Подтверждённые опубликованные списки (исходный текст страниц, изображения и логотипы НЕ включены):

- Английская Премьер-лига (20 клубов): https://www.premierleague.com/en/news/4706139/see-all-the-202627-premier-league-squad-lists
- Real Madrid: https://www.realmadrid.com/en-US/news/football/first-team/latest-news/dorsales-del-real-madrid-para-la-temporada-2026-27-10-08-2026
- FC Barcelona: https://www.fcbarcelona.com/en/football/first-team/news/4570894/202627-first-team-jersey-numbers-confirmed
- Atlético de Madrid: https://en.atleticodemadrid.com/jugadores-primer-equipo/
- FC Bayern: https://fcbayern.com/en/teams/first-team
- Borussia Dortmund: https://www.bvb.de/de/en/news/news-overview/news.html/2026/8/20/These-are-the-jersey-numbers-for-the-2026/27-season.html
- Juventus: https://www.juventus.com/en/teams/first-team-men/squad/
- Napoli: https://sscnapoli.it/en/stagione/rosa
- Paris Saint-Germain: https://www.psg.fr/en/mens-football/squad/season/2026-2027
- Olympique de Marseille: https://www.om.fr/en/team/men

В VELTON сохранён выборочный датированный список *имён и позиций* с указанием страницы-источника, не содержимое страниц, фото, эмблемы или официальные изображения. Никакая из организаций не поддерживает и не спонсирует VELTON. При коммерческом размещении нужно отдельно проверить права на товарные знаки и применимые правила использования данных.


## VELTON v0.9: факультативные статические источники футболистов

- dcaribou/transfermarkt-datasets: https://github.com/dcaribou/transfermarkt-datasets — лицензия проекта CC0 1.0. Датированный срез до 6 июля 2026. Скрипт `tools/install_real_rosters_v09.py` использует только имя, клуб, позицию, дату рождения и национальность для *однократного* преобразования на компьютере оператора. Результаты игр и коммерческие атрибуты не переносятся. CSV не входит в релиз. Условия исходной площадки и применимые права на перепубликацию следует проверить перед коммерческим применением.
- rovnez/FC 26 (FIFA 26) Player Data (Kaggle): https://www.kaggle.com/datasets/rovnez/fc-26-fifa-26-player-data — дополнительные исторические данные можно импортировать только по усмотрению оператора из лично полученного файла, соблюдая условия первоначального источника. Сами CSV, карточки EA, изображения, логотипы и игровые характеристики НЕ включены в VELTON. Это игровой срез, а не официальная заявка 2026/27.
- Ни один из этих источников не является официальным спонсором VELTON и не даёт гарантий актуальности 2026/27.
