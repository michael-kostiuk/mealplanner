"""clean up ingredient nutrition, categories and duplicates; tidy recipe categories

Data-only migration for the owner's database (the demo is rebuilt from its seed).

- Every ingredient gets nutrition per 100 g (or 100 ml for drinks and sauces), a lowercase
  category key the UI translates, and a tidy name. Values are typical reference values.
- Duplicate ingredients are merged into one (recipes and shopping lists are re-pointed).
- Recipe units are normalised ('г' -> 'g', 'unit' -> 'piece', salt "pieces" -> pinch, ...).
- Recipe categories become lowercase keys; the two identical "Піца з лаваша" recipes become
  one; same-named but different recipes get distinct names.

Each change is applied only when the row still has the name it had when this was written, so
anything renamed or deleted in the meantime is left alone.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-11-04 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# id: (current name, new name or None, category, base unit, kcal, protein, carbs, fat) per 100
INGREDIENTS = {
    75: ('Абрикос', None, 'fruits', 'g', 48, 1.4, 11.1, 0.4),
    1: ('Авокадо', None, 'fruits', 'g', 160, 2, 8.5, 14.7),
    94: ('Айсберг', None, 'vegetables', 'g', 14, 0.9, 3, 0.1),
    273: ('Ананас', None, 'fruits', 'g', 50, 0.5, 13.1, 0.1),
    168: ('Арахіс', None, 'nuts', 'g', 567, 25.8, 16.1, 49.2),
    330: ('Багет', None, 'grains', 'g', 270, 9, 52, 3),
    2: ('Баклажан', None, 'vegetables', 'g', 25, 1, 5.9, 0.2),
    3: ('Банан', None, 'fruits', 'g', 89, 1.1, 22.8, 0.3),
    331: ('Батат', None, 'vegetables', 'g', 86, 1.6, 20.1, 0.1),
    5: ('Броколі', None, 'vegetables', 'g', 34, 2.8, 6.6, 0.4),
    217: ('Буряк', None, 'vegetables', 'g', 43, 1.6, 9.6, 0.2),
    191: ('Ваніль', None, 'spices', 'g', 288, 0.1, 12.7, 0.1),
    11: ('Вишня', None, 'fruits', 'g', 50, 1, 12.2, 0.3),
    77: ('Вода', None, 'beverages', 'ml', 0, 0, 0, 0),
    14: ('Гарбуз', None, 'vegetables', 'g', 26, 1, 6.5, 0.1),
    99: ('Гречка', None, 'grains', 'g', 343, 13.3, 71.5, 3.4),
    16: ('Груша', None, 'fruits', 'g', 57, 0.4, 15.2, 0.1),
    87: ('Гірчиця', None, 'condiments', 'g', 66, 4.4, 5.8, 4),
    332: ('Дорадо', None, 'seafood', 'g', 96, 18, 0, 3),
    17: ('Желатин', None, 'baking', 'g', 335, 85.6, 0, 0.1),
    73: ('Жовток', 'Яєчний жовток', 'proteins', 'g', 322, 15.9, 3.6, 26.5),
    19: ('Зелень', None, 'herbs', 'g', 36, 3, 6.3, 0.8),
    23: ('Какао', None, 'baking', 'g', 228, 19.6, 57.9, 13.7),
    24: ('Картопля', None, 'vegetables', 'g', 77, 2, 17.5, 0.1),
    308: ('Квасоля', None, 'legumes', 'g', 333, 23.6, 60, 0.8),
    25: ('Кетчуп', None, 'condiments', 'g', 101, 1, 27.4, 0.1),
    27: ('Кеш’ю', 'Кешʼю', 'nuts', 'g', 553, 18.2, 30.2, 43.9),
    29: ('Кориця', None, 'spices', 'g', 247, 4, 80.6, 1.2),
    119: ('Креветки', None, 'seafood', 'g', 85, 20.1, 0, 0.5),
    30: ('Крохмаль', None, 'baking', 'g', 333, 0.1, 83.1, 0.1),
    124: ('Кріп', None, 'herbs', 'g', 43, 3.5, 7, 1.1),
    31: ('Кунжут', None, 'nuts', 'g', 573, 17.7, 23.4, 49.7),
    305: ('Куркума', None, 'spices', 'g', 312, 9.7, 67.1, 3.3),
    339: ('Кускус', None, 'grains', 'g', 376, 12.8, 77.4, 0.6),
    340: ('Ківі', None, 'fruits', 'g', 61, 1.1, 14.7, 0.5),
    239: ('Кінза', None, 'herbs', 'g', 23, 2.1, 3.7, 0.5),
    82: ('Кіноа', None, 'grains', 'g', 368, 14.1, 64.2, 6.1),
    34: ('Лаваш', None, 'grains', 'g', 275, 9, 56, 1.2),
    35: ('Лимон', None, 'fruits', 'g', 29, 1.1, 9.3, 0.3),
    342: ('Лосось', None, 'seafood', 'g', 208, 20.4, 0, 13.4),
    343: ('Мак', None, 'nuts', 'g', 525, 18, 28.1, 41.6),
    79: ('Макарони', None, 'grains', 'g', 371, 13, 74.7, 1.5),
    36: ('Мед', None, 'condiments', 'g', 304, 0.3, 82.4, 0),
    197: ('Мигдаль', None, 'nuts', 'g', 579, 21.2, 21.6, 49.9),
    344: ('Минтай', None, 'seafood', 'g', 72, 15.9, 0, 0.8),
    38: ('Молоко', None, 'dairy', 'g', 52, 2.9, 4.7, 2.5),
    39: ('Морква', None, 'vegetables', 'g', 41, 0.9, 9.6, 0.2),
    40: ('Моцарела', None, 'dairy', 'g', 300, 22.2, 2.2, 22.4),
    345: ('Нут', None, 'legumes', 'g', 364, 19.3, 60.7, 6),
    131: ('Овочі', None, 'vegetables', 'g', 30, 1.5, 6, 0.2),
    81: ('Огірок', None, 'vegetables', 'g', 15, 0.7, 3.6, 0.1),
    346: ('Оливки', None, 'canned', 'g', 115, 0.8, 6.3, 10.7),
    44: ('Олія', None, 'fats', 'g', 884, 0, 0, 100),
    347: ('Оцет', None, 'condiments', 'ml', 18, 0, 0.1, 0),
    348: ('Паприка', None, 'spices', 'g', 282, 14.1, 54, 12.9),
    95: ('Печінка', 'Печінка яловича', 'meat', 'g', 135, 20.4, 3.9, 3.6),
    349: ('Протеїн', None, 'other', 'g', 380, 75, 10, 5),
    134: ('Прошуто', None, 'meat', 'g', 250, 26, 0.5, 16),
    105: ('пшоно', 'Пшоно', 'grains', 'g', 378, 11, 72.9, 4.2),
    258: ('Рис', None, 'grains', 'g', 360, 6.6, 79.3, 0.6),
    49: ('Розпушувач', None, 'baking', 'g', 53, 0, 27.7, 0),
    91: ('Рукола', None, 'vegetables', 'g', 25, 2.6, 3.7, 0.7),
    164: ('Рікота', None, 'dairy', 'g', 174, 11.3, 3, 13),
    83: ('Салат', None, 'vegetables', 'g', 15, 1.4, 2.9, 0.2),
    72: ('Сало', None, 'meat', 'g', 770, 2.4, 0, 85),
    230: ('Сир', None, 'dairy', 'g', 356, 25, 2, 28),
    127: ('Сода', 'Харчова сода', 'spices', 'g', 0, 0, 0, 0),
    353: ('Сочевиця', None, 'legumes', 'g', 352, 24.6, 63.4, 1.1),
    120: ('Спагетті', None, 'grains', 'g', 371, 13, 74.7, 1.5),
    141: ('Спеції', None, 'spices', 'g', 0, 0, 0, 0),
    218: ('Судак', None, 'seafood', 'g', 84, 18.4, 0, 1.1),
    88: ('Сухарики', None, 'grains', 'g', 400, 11.9, 72, 6.6),
    54: ('Сіль', None, 'spices', 'g', 0, 0, 0, 0),
    354: ('Телятина', None, 'meat', 'g', 172, 24.4, 0, 7.6),
    56: ('Томат', None, 'vegetables', 'g', 18, 0.9, 3.9, 0.2),
    302: ('Тофу', None, 'proteins', 'g', 76, 8, 1.9, 4.8),
    253: ('Форель', None, 'seafood', 'g', 141, 19.9, 0, 6.2),
    198: ('Фініки', None, 'fruits', 'g', 282, 2.5, 75, 0.4),
    224: ('Хек', None, 'seafood', 'g', 86, 17, 0, 2),
    60: ('Хліб', None, 'grains', 'g', 265, 9, 49, 3.2),
    183: ('Хлібці', None, 'grains', 'g', 360, 11, 71, 3),
    106: ('цукор', 'Цукор', 'baking', 'g', 387, 0, 100, 0),
    63: ('Цукрозамінник', None, 'baking', 'g', 20, 0, 5, 0),
    64: ('Цукіні', None, 'vegetables', 'g', 17, 1.2, 3.1, 0.3),
    89: ('Часник', None, 'vegetables', 'g', 149, 6.4, 33.1, 0.5),
    65: ('Шампіньйони', None, 'vegetables', 'g', 22, 3.1, 3.3, 0.3),
    66: ('Шинка', None, 'meat', 'g', 145, 21, 1.5, 6),
    67: ('Шпинат', None, 'vegetables', 'g', 23, 2.9, 3.6, 0.4),
    68: ('Яблуко', None, 'fruits', 'g', 52, 0.3, 13.8, 0.2),
    69: ('Ягоди', None, 'fruits', 'g', 50, 0.7, 12, 0.3),
    70: ('Яйце', None, 'proteins', 'g', 143, 12.6, 0.7, 9.5),
    101: ('Яловичина', None, 'meat', 'g', 250, 26, 0, 15),
    250: ('Ананас консервований', None, 'canned', 'g', 60, 0.4, 15.6, 0.1),
    193: ('Арахісова паста', None, 'nuts', 'g', 588, 25, 20, 50),
    143: ('Болгарський перець', None, 'vegetables', 'g', 27, 1, 6, 0.3),
    301: ('Борошно нутове', None, 'baking', 'g', 387, 22.4, 57.8, 6.7),
    144: ('Борошно пшеничне', None, 'baking', 'g', 364, 10.3, 76.3, 1),
    76: ('Борошно рисове', None, 'baking', 'g', 366, 6, 80.1, 1.4),
    4: ('Борошно цільнозернове', None, 'baking', 'g', 340, 13.2, 72, 2.5),
    98: ('Ванільний цукор', None, 'baking', 'g', 398, 0, 99.5, 0),
    10: ('Вершкове масло', None, 'dairy', 'g', 717, 0.9, 0.1, 81.1),
    154: ('Висівки пшеничні', None, 'grains', 'g', 216, 15.6, 64.5, 4.3),
    12: ('Волоський горіх', None, 'nuts', 'g', 654, 15.2, 13.7, 65.2),
    277: ('Горіхова паста', None, 'nuts', 'g', 600, 20, 20, 50),
    93: ('Грейпфрут ', 'Грейпфрут', 'fruits', 'g', 42, 0.8, 10.7, 0.1),
    251: ('Гірчиця лагідна', None, 'condiments', 'g', 147, 3.8, 9.9, 7.4),
    309: ('Духмяний перець', None, 'spices', 'g', 263, 6.1, 72.1, 8.7),
    133: ('Житній хліб', None, 'grains', 'g', 259, 8.5, 48.3, 3.3),
    165: ('Згущене молоко', None, 'dairy', 'g', 321, 7.9, 54.4, 8.7),
    22: ('Йогурт грецький', None, 'dairy', 'g', 73, 9.9, 3.9, 2),
    184: ('Кава еспресо', None, 'beverages', 'ml', 2, 0.1, 0, 0.2),
    216: ('Капуста білокачанна', None, 'vegetables', 'g', 25, 1.3, 5.8, 0.1),
    327: ('Капуста квашена', None, 'vegetables', 'g', 19, 0.9, 4.3, 0.1),
    333: ('Капуста червона', None, 'vegetables', 'g', 31, 1.4, 7.4, 0.2),
    269: ('Квасоля консервована', None, 'canned', 'g', 91, 6, 16, 0.4),
    334: ('Квасоля стручкова', None, 'vegetables', 'g', 31, 1.8, 7, 0.2),
    28: ('Кокосова стружка', None, 'nuts', 'g', 660, 6.9, 23.7, 64.5),
    203: ('Кокосове молоко', None, 'canned', 'g', 197, 2, 2.8, 21.3),
    300: ('Копчена паприка', None, 'spices', 'g', 282, 14.1, 54, 12.9),
    219: ('Корінь петрушки', None, 'vegetables', 'g', 55, 3, 12.3, 0.6),
    80: ('Кукурудза консервована', None, 'canned', 'g', 81, 2.3, 15.6, 1),
    336: ('Кукурудзяна крупа', None, 'grains', 'g', 370, 8.1, 79.6, 1.2),
    225: ('Кукурудзяний крохмаль', None, 'baking', 'g', 381, 0.3, 91.3, 0.1),
    179: ('Куряча печінка', None, 'meat', 'g', 119, 16.9, 0.7, 4.8),
    32: ('Куряча шинка', None, 'meat', 'g', 110, 17, 2, 3.5),
    256: ('Куряче серце', None, 'meat', 'g', 153, 15.6, 0.1, 9.3),
    33: ('Куряче філе', None, 'meat', 'g', 120, 22.5, 0, 2.6),
    337: ('Курячий фарш', None, 'meat', 'g', 143, 17.4, 0, 8.1),
    338: ('Курячі гомілки', None, 'meat', 'g', 172, 18, 0, 11),
    78: ('Курячі чверті', None, 'meat', 'g', 215, 18, 0, 15.5),
    139: ('Лаваш цільнозерновий', None, 'grains', 'g', 260, 9, 53, 1.7),
    104: ('Лавровий лист', None, 'spices', 'g', 313, 7.6, 75, 8.4),
    341: ('Листи лазаньї', None, 'grains', 'g', 371, 13, 74.7, 1.5),
    266: ('Лист норі', None, 'other', 'g', 35, 5.8, 5.1, 0.3),
    315: ('Листя капусти', None, 'vegetables', 'g', 25, 1.3, 5.8, 0.1),
    287: ('Майонезний соус', None, 'condiments', 'g', 300, 0.5, 4, 31),
    264: ('Маринований огірок', 'Огірок маринований', 'canned', 'g', 12, 0.5, 2.3, 0.2),
    37: ('Мелена вівсянка', None, 'grains', 'g', 379, 13.2, 67.7, 6.5),
    201: ('Мигдалеві пластівці', None, 'nuts', 'g', 579, 21.2, 21.6, 49.9),
    96: ('Мигдальне борошно', None, 'baking', 'g', 571, 21, 20, 50),
    280: ('Морозиво вершкове', None, 'frozen', 'g', 207, 3.5, 23.6, 11),
    281: ('Морозиво пломбір', None, 'frozen', 'g', 232, 3.2, 20.8, 15),
    288: ('Морський коктейль', None, 'seafood', 'g', 85, 16, 1.5, 1.5),
    234: ('Мускатний горіх', None, 'spices', 'g', 525, 5.8, 49.3, 36.3),
    295: ('Мікс салатів', None, 'vegetables', 'g', 17, 1.3, 3.3, 0.2),
    129: ('Напівтвердий сир', None, 'dairy', 'g', 350, 25, 0, 28),
    235: ('Насіння гарбуза', None, 'nuts', 'g', 559, 30.2, 10.7, 49),
    41: ('Насіння льону', None, 'nuts', 'g', 534, 18.3, 28.9, 42.2),
    42: ('Насіння соняшникове', None, 'nuts', 'g', 584, 20.8, 20, 51.5),
    43: ('Насіння чіа', None, 'nuts', 'g', 486, 16.5, 42.1, 30.7),
    293: ('Огірок солоний', None, 'canned', 'g', 12, 0.5, 2.2, 0.2),
    84: ('Оливкова олія', None, 'fats', 'g', 884, 0, 0, 100),
    296: ('Орегано сушений', None, 'spices', 'g', 265, 9, 68.9, 4.3),
    291: ('Оцет бальзамічний', None, 'condiments', 'ml', 88, 0.5, 17, 0),
    265: ('Оцет рисовий', None, 'condiments', 'ml', 18, 0, 0.1, 0),
    228: ('Пекінська капуста', None, 'vegetables', 'g', 16, 1.2, 3.2, 0.2),
    152: ('Петрушка свіжа', None, 'herbs', 'g', 36, 3, 6.3, 0.8),
    46: ('Плавлений сир', None, 'dairy', 'g', 290, 25, 2, 22),
    236: ('Помідори чері', None, 'vegetables', 'g', 18, 0.9, 3.9, 0.2),
    350: ('Пшенична крупа', None, 'grains', 'g', 340, 11, 72, 1.5),
    317: ('Рис басматі', None, 'grains', 'g', 360, 7.5, 78, 0.9),
    210: ('Рисова локшина', None, 'grains', 'g', 364, 6, 80, 0.6),
    103: ('Розмарин гілочка', 'Розмарин (гілочки)', 'herbs', 'g', 131, 3.3, 20.7, 5.9),
    303: ('Рослинне молоко', None, 'beverages', 'ml', 45, 1, 6, 2),
    245: ('Селера стеблова', None, 'vegetables', 'g', 16, 0.7, 3, 0.2),
    262: ('Сир брі', None, 'dairy', 'g', 334, 20.8, 0.5, 27.7),
    135: ('Сир камамбер', None, 'dairy', 'g', 300, 19.8, 0.5, 24.3),
    180: ('Сир кисломолочний', None, 'dairy', 'g', 121, 17, 1.8, 5),
    155: ('Сирні млинці', None, 'other', 'g', 220, 12, 22, 9),
    324: ('Сироп агави', None, 'condiments', 'ml', 310, 0, 76, 0),
    351: ('Сир сулугуні', None, 'dairy', 'g', 290, 20, 0, 24),
    51: ('Сир твердий', None, 'dairy', 'g', 356, 25, 2, 28),
    241: ('Сир фета', None, 'dairy', 'g', 264, 14.2, 4.1, 21.3),
    263: ('Сир чедер', None, 'dairy', 'g', 403, 24.9, 1.3, 33.1),
    167: ('Солона карамель', None, 'condiments', 'g', 380, 2, 70, 10),
    53: ('Соєвий соус', None, 'condiments', 'ml', 53, 8.1, 4.9, 0.6),
    267: ('Сухарі панко', None, 'grains', 'g', 395, 13, 77, 3.5),
    204: ('Сушений часник', None, 'spices', 'g', 331, 16.6, 72.7, 0.7),
    284: ('Сік ананасовий', None, 'beverages', 'ml', 53, 0.4, 12.9, 0.1),
    255: ('Сік апельсиновий', None, 'beverages', 'ml', 45, 0.7, 10.4, 0.2),
    321: ('Сік лайма', None, 'condiments', 'ml', 25, 0.4, 8.4, 0.1),
    57: ('Томатна паста', None, 'canned', 'g', 82, 4.3, 18.9, 0.5),
    316: ('Тофу копчений', None, 'proteins', 'g', 150, 15, 2, 9),
    181: ('Тісто філо', None, 'baking', 'g', 299, 7.1, 52.6, 6),
    268: ('Форель слабосолена', None, 'seafood', 'g', 186, 21, 0, 11),
    356: ('Філе індички', None, 'meat', 'g', 114, 23.7, 0, 1.5),
    149: ('Хліб цільнозерновий', None, 'grains', 'g', 252, 12.4, 43, 3.5),
    298: ('Хумус класичний', None, 'legumes', 'g', 166, 7.9, 14.3, 9.6),
    61: ('Цвітна капуста', None, 'vegetables', 'g', 25, 1.9, 5, 0.3),
    160: ('Цедра лимона', None, 'fruits', 'g', 47, 1.5, 16, 0.3),
    357: ('Цибуля зелена', None, 'vegetables', 'g', 32, 1.8, 7.3, 0.2),
    157: ('Цибуля ріпчаста', None, 'vegetables', 'g', 40, 1.1, 9.3, 0.1),
    237: ('Червона цибуля', None, 'vegetables', 'g', 40, 1.1, 9.3, 0.1),
    319: ('Чилі пластівці', None, 'spices', 'g', 314, 12, 56.6, 14.3),
    285: ('Чорний перець', None, 'spices', 'g', 251, 10.4, 64, 3.3),
    226: ('Яловича вирізка', None, 'meat', 'g', 158, 21, 0, 8),
    212: ('Яловича лопатка', None, 'meat', 'g', 180, 20, 0, 11),
    71: ('Яєчний білок', None, 'proteins', 'g', 52, 10.9, 0.7, 0.2),
    211: ('Імбир свіжий', None, 'vegetables', 'g', 80, 1.8, 17.8, 0.8),
    7: ('Булочка для бургера', None, 'grains', 'g', 279, 9.6, 49, 4.3),
    254: ('Вода або бульйон', None, 'beverages', 'ml', 5, 0.5, 0.4, 0.2),
    304: ('Гливи або печериці', None, 'vegetables', 'g', 30, 3.2, 5, 0.4),
    292: ('Горошок зелений консервований', None, 'canned', 'g', 69, 4.5, 12.6, 0.4),
    282: ('Куряче філе копчене', None, 'meat', 'g', 117, 19, 1, 4),
    320: ('Кінза або петрушка', None, 'herbs', 'g', 30, 2.5, 5, 0.6),
    196: ('Молоко сухе знежирене', None, 'dairy', 'g', 362, 36.2, 52, 0.8),
    102: ('Червоне сухе вино', None, 'beverages', 'ml', 85, 0.1, 2.6, 0),
    294: ('Гірчиця французька в зернах', None, 'condiments', 'g', 150, 7, 5, 10),
    238: ('Мікс салату або шпинат', None, 'vegetables', 'g', 20, 2, 3.4, 0.3),
    192: ('Пюре яблучне без цукру', None, 'fruits', 'g', 42, 0.2, 11.3, 0.1),
    146: ('Томати у власному соку', None, 'canned', 'g', 21, 0.9, 4, 0.2),
    174: ('Тунець у власному соку', None, 'canned', 'g', 116, 25.5, 0, 0.8),
    58: ('Фарш з яловичої вирізки', None, 'meat', 'g', 198, 19.4, 0, 12.7),
    156: ('Куряче філе стегна (без шкіри)', None, 'meat', 'g', 121, 19.7, 0, 4.1),
    283: ('Майонезний соус делікатесний 28%', None, 'condiments', 'g', 280, 0.5, 5, 28),
    162: ("Сир кисломолочний м'який 4,5%", None, 'dairy', 'g', 118, 16, 2, 4.5),
    328: ('Рослинне молоко (кокосове)', None, 'beverages', 'ml', 24, 0.2, 2.9, 1.2),
    311: ('Соєвий фарш (сухий)', None, 'proteins', 'g', 327, 52, 30, 1),
    195: ('Йогурт білий 1,6%', None, 'dairy', 'g', 51, 4.3, 6, 1.6),
    163: ('Йогурт питний 1,6%', None, 'dairy', 'g', 60, 2.8, 9, 1.6),
    123: ('Йогурт білий 3%', None, 'dairy', 'g', 64, 4, 5.5, 3),
    126: ('Сир кисломолочний 5%', None, 'dairy', 'g', 121, 17, 1.8, 5),
    170: ('Йогурт білий 8%', None, 'dairy', 'g', 115, 3.5, 5, 9),
    194: ('Шоколад чорний 80%', None, 'snacks', 'g', 598, 7.8, 45.9, 42.6),
    271: ('Морква по-корейськи', None, 'vegetables', 'g', 130, 1, 8, 10),
    290: ('Мікс бебі-шпинату та мангольду', None, 'vegetables', 'g', 21, 2.3, 3.5, 0.3),
    279: ('Рослинне молоко, вода', None, 'beverages', 'ml', 20, 0.5, 3, 0.7),
    186: ('Стиглий банан, ягоди', None, 'fruits', 'g', 70, 1, 17, 0.3),
    223: ('Мускатний горіх, сіль, спеції', None, 'spices', 'g', 0, 0, 0, 0),
    260: ('Сушений імбир, сіль, спеції', None, 'spices', 'g', 0, 0, 0, 0),
    322: ('Спеції (паприка копчена, кумін)', None, 'spices', 'g', 0, 0, 0, 0),
    6: ('Булгур (суха вага)', None, 'grains', 'g', 342, 12.3, 75.9, 1.3),
    335: ('Крупа (на вибір)', None, 'grains', 'g', 340, 11, 72, 2),
    307: ('Спеції (куркума, сухий часник)', None, 'spices', 'g', 0, 0, 0, 0),
    259: ('Овочі (перець, цибуля)', None, 'vegetables', 'g', 30, 1, 6.5, 0.2),
    314: ('Спеції (паприка, орегано)', None, 'spices', 'g', 0, 0, 0, 0),
    48: ('Рис (готовий)', None, 'grains', 'g', 130, 2.7, 28.2, 0.3),
    207: ('Чебрець (тім’ян), мускатний горіх', None, 'spices', 'g', 0, 0, 0, 0),
    278: ('Сік лимона/лайма', None, 'condiments', 'ml', 22, 0.4, 6.9, 0.2),
    8: ('Вершки 10%', None, 'dairy', 'g', 119, 3, 4, 10),
    248: ('Сметана 10%', None, 'dairy', 'g', 115, 3, 2.9, 10),
    247: ('Вершки 15%', None, 'dairy', 'ml', 160, 2.8, 3.7, 15),
    52: ('Сметана 15%', None, 'dairy', 'g', 158, 2.6, 3, 15),
    26: ('Кефір 2,5%', None, 'dairy', 'g', 53, 2.9, 4, 2.5),
    21: ('Йогурт 2%', None, 'dairy', 'g', 60, 4.3, 6.2, 2),
    9: ('Вершки 20%', None, 'dairy', 'g', 205, 2.8, 3.7, 20),
    352: ('Соус zero', None, 'condiments', 'g', 20, 0.5, 4, 0),
    136: ('Крем-сир', None, 'dairy', 'g', 342, 6, 4.1, 34),
    148: ('Цибуля-порей', None, 'vegetables', 'g', 61, 1.5, 14.2, 0.3),
    187: ("М'ята", 'Мʼята', 'herbs', 'g', 70, 3.8, 14.9, 0.9),
    173: ('Рікота, плавлений сир', None, 'dairy', 'g', 230, 14, 4, 17),
    166: ("Маскарпоне, сир кисломолочний, м'який", None, 'dairy', 'g', 250, 10, 3, 22),
    151: ('Орегано, сухий часник', None, 'spices', 'g', 0, 0, 0, 0),
    205: ('Зелень, спеції', None, 'spices', 'g', 0, 0, 0, 0),
    310: ('Сіль, зелень', None, 'spices', 'g', 0, 0, 0, 0),
    159: ('Сіль, перець', None, 'spices', 'g', 0, 0, 0, 0),
    122: ('Сіль, спеції', None, 'spices', 'g', 0, 0, 0, 0),
    128: ('Сіль, трави', None, 'spices', 'g', 0, 0, 0, 0),
    138: ('Зелень, сіль, спеції', None, 'spices', 'g', 0, 0, 0, 0),
    270: ('Паприка, сіль, перець', None, 'spices', 'g', 0, 0, 0, 0),
    229: ('Паприка, сіль, спеції', None, 'spices', 'g', 0, 0, 0, 0),
    272: ('Сіль, карі, паприка', None, 'spices', 'g', 0, 0, 0, 0),
    227: ('Сіль, коріандр, перець', None, 'spices', 'g', 0, 0, 0, 0),
    261: ('Сіль, орегано, базилік', None, 'spices', 'g', 0, 0, 0, 0),
    244: ('Сіль, орегано, перець', None, 'spices', 'g', 0, 0, 0, 0),
    231: ('Сіль, паприка, перець', None, 'spices', 'g', 0, 0, 0, 0),
    232: ('Сіль, перець, зелень', None, 'spices', 'g', 0, 0, 0, 0),
    233: ('Сіль, перець, сушений часник, паприка', None, 'spices', 'g', 0, 0, 0, 0),
}

# (duplicate id, its current name, id to keep): the duplicate is folded into the kept row
INGREDIENT_MERGES = [
    (313, 'Окріп', 77),
    (246, 'Окроп', 77),
    (158, 'Вода (крижана)', 77),
    (18, 'Желатин швидкорозчинний', 17),
    (50, 'Рослинна олія', 44),
    (74, 'Мʼякий творог', 162),
    (100, 'Перець', 143),
    (293, 'Огірок солоний', 264),
]

# Recipe units that are spelled differently or are not real units
RECIPE_UNIT_ALIASES = {'г': 'g', 'дрібка': 'pinch', 'to смак': 'to taste'}

# (ingredient id, current unit, new unit, quantity multiplier); applied before 'unit' -> 'piece'
RECIPE_UNIT_FIXES = [
    (49, 'piece', 'tsp', 2),  # half a sachet of baking powder is about a teaspoon
    (54, 'piece', 'pinch', 1),  # "1 piece" of salt
    (54, 'unit', 'to taste', 1),
    (191, 'unit', 'to taste', 1),
    (29, 'unit', 'to taste', 1),
    (141, 'unit', 'to taste', 1),
    (63, 'unit', 'to taste', 1),
    (300, 'unit', 'to taste', 1),
    (234, 'unit', 'to taste', 1),
    (159, 'unit', 'to taste', 1),
    (122, 'unit', 'to taste', 1),
    (89, 'unit', 'clove', 1),
    (89, 'slice', 'clove', 1),
    (19, 'unit', 'bunch', 1),
    (91, 'unit', 'bunch', 1),
    (124, 'unit', 'g', 2),  # sprigs of dill, coriander and mint, about 2 g each
    (239, 'unit', 'g', 2),
    (187, 'unit', 'g', 2),
]

RECIPE_CATEGORIES = {
    'breakfast': 'breakfast',
    'каші': 'breakfast',
    'lunch': 'lunch',
    'основні страви': 'lunch',
    'main': 'lunch',
    'dinner': 'dinner',
    'dessert': 'dessert',
    'salad': 'salad',
    'soup': 'soup',
    'суп': 'soup',
    'snack': 'snack',
    'drink': 'drink',
}

# (duplicate recipe id, name, recipe id to keep): same dish saved twice
RECIPE_MERGES = [(25, 'Піца з лаваша', 7)]

# Different dishes that share a name
RECIPE_RENAMES = [
    (160, 'Бургер', 'Бургер з яловичиною'),
    (40, 'Бургер', 'Бургер з куркою'),
    (159, 'Грибний крем-суп', 'Грибний крем-суп з картоплею'),
    (38, 'Грибний крем-суп', 'Грибний крем-суп з борошном'),
]


def _has(conn, table: str, row_id: int, name: str) -> bool:
    found = conn.execute(
        sa.text(f"SELECT name FROM {table} WHERE id = :id"), {"id": row_id}
    ).scalar()
    return found is not None and found.strip() == name.strip()


def _merge_ingredient(conn, dup: int, keep: int) -> None:
    params = {"dup": dup, "keep": keep}
    # A recipe can list each ingredient once: add amounts in the same unit, then drop the rest
    conn.execute(
        sa.text(
            "UPDATE recipe_ingredients k SET quantity = k.quantity + d.quantity "
            "FROM recipe_ingredients d WHERE k.ingredient_id = :keep AND d.ingredient_id = :dup "
            "AND d.recipe_id = k.recipe_id AND d.unit = k.unit"
        ),
        params,
    )
    conn.execute(
        sa.text(
            "DELETE FROM recipe_ingredients d WHERE d.ingredient_id = :dup AND EXISTS ("
            "SELECT 1 FROM recipe_ingredients k WHERE k.recipe_id = d.recipe_id "
            "AND k.ingredient_id = :keep)"
        ),
        params,
    )
    conn.execute(
        sa.text("UPDATE recipe_ingredients SET ingredient_id = :keep WHERE ingredient_id = :dup"),
        params,
    )
    conn.execute(
        sa.text("UPDATE shopping_list_items SET ingredient_id = :keep WHERE ingredient_id = :dup"),
        params,
    )
    conn.execute(sa.text("DELETE FROM ingredient_portions WHERE ingredient_id = :dup"), params)
    conn.execute(sa.text("DELETE FROM ingredients WHERE id = :dup"), params)


def _merge_recipe(conn, dup: int, keep: int) -> None:
    params = {"dup": dup, "keep": keep}
    conn.execute(
        sa.text("UPDATE meal_plan_entries SET recipe_id = :keep WHERE recipe_id = :dup"), params
    )
    conn.execute(
        sa.text(
            "DELETE FROM favorites d WHERE d.recipe_id = :dup AND EXISTS ("
            "SELECT 1 FROM favorites k WHERE k.user_id = d.user_id AND k.recipe_id = :keep)"
        ),
        params,
    )
    conn.execute(sa.text("UPDATE favorites SET recipe_id = :keep WHERE recipe_id = :dup"), params)
    # The kept recipe can be picked for every meal either copy was used for
    conn.execute(
        sa.text(
            "UPDATE recipes k SET breakfast_weight = GREATEST(k.breakfast_weight, d.breakfast_weight), "
            "lunch_weight = GREATEST(k.lunch_weight, d.lunch_weight), "
            "dinner_weight = GREATEST(k.dinner_weight, d.dinner_weight) "
            "FROM recipes d WHERE k.id = :keep AND d.id = :dup"
        ),
        params,
    )
    conn.execute(sa.text("DELETE FROM recipes WHERE id = :dup"), params)


def upgrade() -> None:
    """Upgrade data."""
    conn = op.get_bind()

    for dup, name, keep in INGREDIENT_MERGES:
        keep_exists = conn.execute(
            sa.text("SELECT 1 FROM ingredients WHERE id = :id"), {"id": keep}
        ).scalar()
        if keep_exists and _has(conn, "ingredients", dup, name):
            _merge_ingredient(conn, dup, keep)

    for ingredient_id, row in INGREDIENTS.items():
        old_name, new_name, category, base_unit, calories, protein, carbs, fats = row
        if not _has(conn, "ingredients", ingredient_id, old_name):
            continue
        conn.execute(
            sa.text(
                "UPDATE ingredients SET name = :name, category = :category, base_unit = :base_unit, "
                "calories = :calories, protein = :protein, carbs = :carbs, fats = :fats "
                "WHERE id = :id"
            ),
            {
                "id": ingredient_id,
                "name": new_name or old_name.strip(),
                "category": category,
                "base_unit": base_unit,
                "calories": calories,
                "protein": protein,
                "carbs": carbs,
                "fats": fats,
            },
        )

    for old, new in RECIPE_UNIT_ALIASES.items():
        conn.execute(
            sa.text("UPDATE recipe_ingredients SET unit = :new WHERE unit = :old"),
            {"old": old, "new": new},
        )
    for ingredient_id, old_unit, new_unit, factor in RECIPE_UNIT_FIXES:
        conn.execute(
            sa.text(
                "UPDATE recipe_ingredients SET unit = :new_unit, quantity = quantity * :factor "
                "WHERE ingredient_id = :id AND unit = :old_unit"
            ),
            {"id": ingredient_id, "old_unit": old_unit, "new_unit": new_unit, "factor": factor},
        )
    conn.execute(sa.text("UPDATE recipe_ingredients SET unit = 'piece' WHERE unit = 'unit'"))

    for dup, name, keep in RECIPE_MERGES:
        if _has(conn, "recipes", dup, name) and _has(conn, "recipes", keep, name):
            _merge_recipe(conn, dup, keep)

    for recipe_id, old_name, new_name in RECIPE_RENAMES:
        if _has(conn, "recipes", recipe_id, old_name):
            conn.execute(
                sa.text("UPDATE recipes SET name = :name WHERE id = :id"),
                {"id": recipe_id, "name": new_name},
            )

    for old, new in RECIPE_CATEGORIES.items():
        conn.execute(
            sa.text("UPDATE recipes SET category = :new WHERE lower(trim(category)) = :old"),
            {"old": old, "new": new},
        )


def downgrade() -> None:
    """The old values were inconsistent; restore from the backup taken before deploying."""
