# -*- coding: utf-8 -*-
import argparse
import sys

def validate_arguments(args):
    """Валидация параметров с обработкой ошибок"""
    errors = []
    
    # Валидация URL/пути репозитория
    if not (args.repo_url.startswith(('http://', 'https://', 'file://')) or args.repo_url.startswith('/')):
        errors.append("Ошибка: Некорректный формат URL/пути (--repo_url). "
                      "Должен начинаться с http://, https://, file:// или /")
    
    # Валидация версии
    if args.version:
        if not args.version.replace('.', '').isdigit():
            errors.append("Ошибка: Некорректный формат версии (--version). "
                          "Должна состоять из цифр и точек (например: 1.2.3)")
    
    return errors

def main():
    parser = argparse.ArgumentParser(
        description='Минимальное CLI-приложение с настраиваемыми параметрами',
        formatter_class=argparse.RawTextHelpFormatter,
        exit_on_error=False  # Отключаем автоматический выход при ошибках
    )
    
    # Определение параметров с подсказками
    parser.add_argument(
        '--package_name',
        type=str,
        required=True,
        help='Имя анализируемого пакета (обязательный)'
    )
    parser.add_argument(
        '--repo_url',
        type=str,
        required=True,
        help='URL репозитория или путь к файлу (должен начинаться с http://, https://, file:// или /)'
    )
    parser.add_argument(
        '--mode',
        type=str,
        choices=['clone', 'download', 'local'],
        required=True,
        help='Режим работы:\n'
             '  clone    - клонировать репозиторий\n'
             '  download - скачать архив\n'
             '  local    - использовать локальный путь'
    )
    parser.add_argument(
        '--version',
        type=str,
        help='Версия пакета (формат: X.Y.Z)'
    )
    parser.add_argument(
        '--filter_substring',
        type=str,
        help='Подстрока для фильтрации пакетов (необязательная)'
    )
    
    # Обработка запроса справки
    if '-h' in sys.argv or '--help' in sys.argv:
        parser.print_help()
        sys.exit(0)
    
    # Парсинг аргументов с ручной обработкой ошибок
    try:
        args = parser.parse_args()
    except argparse.ArgumentError as e:
        print(f"\nОшибка: {e}")
        print("\n!!! ИСПОЛЬЗОВАНИЕ ПРОГРАММЫ !!!")
        parser.print_help()
        sys.exit(1)
    except SystemExit:
        # Перехватываем только ошибки валидации, но не справку
        if '--help' not in sys.argv and '-h' not in sys.argv:
            print("\n!!! ИСПОЛЬЗОВАНИЕ ПРОГРАММЫ !!!")
            parser.print_help()
        sys.exit(1)
    
    # Валидация дополнительных параметров
    errors = validate_arguments(args)
    if errors:
        print("\nОБНАРУЖЕНЫ ОШИБКИ В ПАРАМЕТРАХ:")
        for error in errors:
            print(f"- {error}")
        print("\n!!! ИСПОЛЬЗОВАНИЕ ПРОГРАММЫ !!!")
        parser.print_help()
        sys.exit(1)
    
    # Вывод параметров в формате ключ-значение
    print("\nНАСТРОЕННЫЕ ПАРАМЕТРЫ:")
    print(f"package_name      = {args.package_name}")
    print(f"repo_url          = {args.repo_url}")
    print(f"mode              = {args.mode}")
    print(f"version           = {args.version or 'не указана'}")
    print(f"filter_substring  = {args.filter_substring or 'не указана'}")
    print("\nПриложение готово к работе!")

if __name__ == "__main__":
    main()
