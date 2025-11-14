# -*- coding: utf-8 -*-
import argparse
import sys
import urllib.request
import gzip
import bz2
import os
import re

def fetch_packages_data(repo_url):
    """Загрузка и распаковка файла Packages из репозитория"""
    try:
        # Обработка локальных путей
        if repo_url.startswith(('http://', 'https://')):
            with urllib.request.urlopen(repo_url, timeout=10) as response:
                content = response.read()
                content_type = response.headers.get('Content-Type', '')
                content_encoding = response.headers.get('Content-Encoding', '')
        else:
            # Локальный файл
            if not os.path.exists(repo_url):
                raise FileNotFoundError(f"Файл не найден: {repo_url}")
            
            with open(repo_url, 'rb') as f:
                content = f.read()
            
            # Определяем тип сжатия по расширению
            if repo_url.endswith('.gz'):
                content_type = 'application/gzip'
            elif repo_url.endswith('.bz2'):
                content_type = 'application/x-bzip2'
            else:
                content_type = 'text/plain'
            content_encoding = ''
        
        # Распаковка данных
        if '.gz' in repo_url or 'gzip' in content_type.lower() or 'gzip' in content_encoding.lower():
            return gzip.decompress(content).decode('utf-8', errors='ignore')
        elif '.bz2' in repo_url or 'bzip2' in content_type.lower() or 'bzip2' in content_encoding.lower():
            return bz2.decompress(content).decode('utf-8', errors='ignore')
        else:
            return content.decode('utf-8', errors='ignore')
    
    except Exception as e:
        raise RuntimeError(f"Ошибка загрузки данных из репозитория: {str(e)}")

def parse_packages_data(packages_data, target_package, target_version):
    """Парсинг данных о пакетах и поиск зависимостей"""
    current_block = {}
    blocks = re.split(r'\n\s*\n', packages_data.strip())
    
    for block in blocks:
        lines = block.split('\n')
        package = None
        version = None
        depends = None
        architecture = None
        
        for line in lines:
            if not line.strip():
                continue
                
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                
                if key == 'Package':
                    package = value
                elif key == 'Version':
                    version = value
                elif key == 'Depends':
                    depends = value
                elif key == 'Architecture':
                    architecture = value
        
        # Сохраняем данные о пакете
        if package and version:
            # Создаем уникальный ключ с архитектурой для избежания коллизий
            pkg_key = f"{package}:{architecture}" if architecture else package
            
            if pkg_key not in current_block:
                current_block[pkg_key] = []
            
            current_block[pkg_key].append({
                'version': version,
                'depends': depends,
                'architecture': architecture
            })
    
    # Формируем ключ для поиска
    search_key = f"{target_package}:amd64"  # Стандартная архитектура для Ubuntu
    
    # Ищем пакет
    if search_key in current_block:
        pkg_versions = current_block[search_key]
    elif target_package in current_block:
        pkg_versions = current_block[target_package]
    else:
        available_packages = [pkg.split(':')[0] for pkg in current_block.keys()]
        raise ValueError(
            f"Пакет '{target_package}' не найден в репозитории. "
            f"Доступные пакеты (примеры): {', '.join(available_packages[:5])}..."
        )
    
    # Ищем точное совпадение версии
    for pkg_data in pkg_versions:
        if pkg_data['version'] == target_version:
            return pkg_data.get('depends', '')
    
    # Ищем частичное совпадение (на случай если указана не полная версия)
    for pkg_data in pkg_versions:
        if target_version in pkg_data['version']:
            return pkg_data.get('depends', '')
    
    # Если не найдено, показываем доступные версии
    available_versions = [pkg['version'] for pkg in pkg_versions]
    raise ValueError(
        f"Версия '{target_version}' пакета '{target_package}' не найдена. "
        f"Доступные версии: {', '.join(available_versions[:5])}..."
    )

def extract_dependencies(depends_string):
    """Извлечение списка зависимостей из строки Depends"""
    if not depends_string:
        return []
    
    dependencies = set()  # Используем set для уникальности
    
    # Разделяем по запятым и обрабатываем каждую зависимость
    for dep_group in depends_string.split(','):
        dep_group = dep_group.strip()
        if not dep_group:
            continue
        
        # Обрабатываем альтернативные зависимости (разделенные |)
        alternatives = dep_group.split('|')
        for alt in alternatives:
            alt = alt.strip()
            if not alt:
                continue
            
            # Извлекаем имя пакета (до первого пробела или скобки)
            dep_name = re.split(r'[ (]', alt)[0].strip()
            
            # Пропускаем виртуальные пакеты и некорректные имена
            if dep_name and not dep_name.startswith('<') and not dep_name.endswith('>'):
                dependencies.add(dep_name)
    
    return sorted(list(dependencies))

def validate_arguments(args):
    """Валидация параметров с обработкой ошибок"""
    errors = []
    
    if not args.version:
        errors.append("Ошибка: Для этого этапа обязательным является параметр --version")
    
    # Валидация URL/пути репозитория
    if not args.repo_url.startswith(('http://', 'https://', 'file://')) and not os.path.exists(args.repo_url):
        errors.append("Ошибка: Некорректный URL/путь репозитория (--repo_url). "
                      "Должен быть действительным URL или существующим локальным файлом")
    
    return errors

def main():
    parser = argparse.ArgumentParser(
        description='Анализ зависимостей пакетов Ubuntu',
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False
    )
    
    # Отдельная обработка справки
    if '-h' in sys.argv or '--help' in sys.argv:
        print("Использование: app.py --package_name <имя> --repo_url <url/путь> --version <версия> [--mode <режим>]")
        print("\nОбязательные параметры:")
        print("  --package_name <имя>    Имя анализируемого пакета")
        print("  --repo_url <url/путь>   URL репозитория или путь к файлу Packages")
        print("  --version <версия>      Версия пакета в формате Ubuntu (например: 1.18.0-6ubuntu14.4)")
        print("\nДополнительные параметры:")
        print("  --mode <режим>          Режим работы (clone/download/local) - для совместимости с предыдущими этапами")
        print("  -h, --help              Показать эту справку")
        sys.exit(0)
    
    # Определение параметров
    parser.add_argument('--package_name', type=str, required=True)
    parser.add_argument('--repo_url', type=str, required=True)
    parser.add_argument('--version', type=str, required=True)
    parser.add_argument('--mode', type=str, choices=['clone', 'download', 'local'], default='download')
    
    # Парсинг аргументов
    try:
        args = parser.parse_args()
    except SystemExit:
        print("\n!!! ИСПОЛЬЗОВАНИЕ ПРОГРАММЫ !!!")
        parser.print_help()
        sys.exit(1)
    
    # Валидация
    errors = validate_arguments(args)
    if errors:
        print("\nОБНАРУЖЕНЫ ОШИБКИ В ПАРАМЕТРАХ:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)
    
    try:
        # Загрузка данных из репозитория
        print(f"\n[+] Загрузка данных из: {args.repo_url}")
        packages_data = fetch_packages_data(args.repo_url)
        
        # Поиск зависимостей
        print(f"[+] Поиск пакета '{args.package_name}' версии '{args.version}'")
        depends_field = parse_packages_data(packages_data, args.package_name, args.version)
        
        # Извлечение зависимостей
        dependencies = extract_dependencies(depends_field)
        
        # Вывод результатов
        print(f"\nНАЙДЕНЫ ЗАВИСИМОСТИ ДЛЯ {args.package_name} (версия {args.version}):")
        if dependencies:
            print("\nПрямые зависимости:")
            for i, dep in enumerate(dependencies, 1):
                print(f"{i}. {dep}")
        else:
            print("Прямые зависимости отсутствуют")
        
        print(f"\nВсего найдено прямых зависимостей: {len(dependencies)}")
        print(f"\nПоле Depends: {depends_field or 'отсутствует'}")
    
    except Exception as e:
        print(f"\nКРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
