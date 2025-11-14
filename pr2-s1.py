# -*- coding: utf-8 -*-
import argparse
import sys
import urllib.request
import gzip
import bz2
import os
import re

def fetch_packages_data(repo_url):
    """Загрузка данных репозитория"""
    try:
        if repo_url.startswith(('http://', 'https://')):
            headers = {'User-Agent': 'Mozilla/5.0 (Ubuntu)'}
            req = urllib.request.Request(repo_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read()
        else:
            if not os.path.exists(repo_url):
                raise FileNotFoundError(f"Файл не найден: {repo_url}")
            with open(repo_url, 'rb') as f:
                content = f.read()
        
        # Автоматическая распаковка
        if repo_url.endswith('.gz') or b'\x1f\x8b' == content[:2]:
            return gzip.decompress(content).decode('utf-8', errors='ignore')
        elif repo_url.endswith('.bz2') or b'BZh' == content[:3]:
            return bz2.decompress(content).decode('utf-8', errors='ignore')
        else:
            return content.decode('utf-8', errors='ignore')
    
    except Exception as e:
        raise RuntimeError(f"Ошибка загрузки данных: {str(e)}")

def parse_packages_index(packages_data):
    """Парсинг индекса пакетов в словарь"""
    packages = {}
    blocks = re.split(r'\n\s*\n', packages_data.strip())
    
    for block in blocks:
        pkg_info = {}
        lines = block.split('\n')
        for line in lines:
            if ':' in line:
                key, value = line.split(':', 1)
                pkg_info[key.strip()] = value.strip()
        
        if 'Package' in pkg_info and 'Version' in pkg_info:
            pkg_key = f"{pkg_info['Package']}:{pkg_info.get('Architecture', 'all')}"
            packages[pkg_key] = pkg_info
    
    return packages

def extract_direct_dependencies(depends_field):
    """Извлечение прямых зависимостей из поля Depends"""
    if not depends_field:
        return []
    
    dependencies = []
    for dep_group in depends_field.split(','):
        alternatives = [alt.strip().split()[0] for alt in dep_group.split('|') if alt.strip()]
        if alternatives:
            dependencies.append(alternatives[0])  # Берем первый вариант из альтернатив
    return list(set(dependencies))  # Убираем дубликаты

def load_test_graph(file_path):
    """Загрузка тестового графа из файла"""
    graph = {}
    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if ':' not in line:
                    continue
                
                package, deps = line.split(':', 1)
                package = package.strip().upper()
                deps_list = [dep.strip().upper() for dep in deps.split(',') if dep.strip()]
                graph[package] = deps_list
        return graph
    except Exception as e:
        raise RuntimeError(f"Ошибка загрузки тестового графа: {str(e)}")

def dfs_build_graph(package, graph, filter_substring, visited=None, current_path=None, result=None):
    """Построение графа зависимостей с DFS и обнаружением циклов"""
    if visited is None:
        visited = set()
    if current_path is None:
        current_path = []
    if result is None:
        result = {}
    
    # Фильтрация по подстроке
    if filter_substring and filter_substring in package:
        return result
    
    # Проверка цикла
    if package in current_path:
        cycle_path = ' -> '.join(current_path + [package])
        raise RuntimeError(f"Обнаружена циклическая зависимость: {cycle_path}")
    
    # Пропускаем уже обработанные пакеты
    if package in visited:
        return result
    
    visited.add(package)
    current_path.append(package)
    
    # Инициализация узла в графе
    if package not in result:
        result[package] = []
    
    # Обработка зависимостей
    dependencies = graph.get(package, [])
    for dep in dependencies:
        # Рекурсивный вызов для транзитивных зависимостей
        dfs_build_graph(dep, graph, filter_substring, visited, current_path, result)
        # Добавление ребра в граф
        if dep not in filter_substring:
            result[package].append(dep)
    
    current_path.pop()
    return result

def print_dependency_graph(graph, root_package):
    """Вывод графа зависимостей в текстовом формате"""
    def print_node(package, indent="", visited=None):
        if visited is None:
            visited = set()
        if package in visited:
            return
        visited.add(package)
        print(f"{indent}{package}")
        for dep in graph.get(package, []):
            print_node(dep, indent + "  ├── ", visited)
    
    print(f"\nГРАФ ЗАВИСИМОСТЕЙ ДЛЯ {root_package}:")
    print_node(root_package)
    print("\nСтруктура графа (ребра):")
    for pkg, deps in graph.items():
        if deps:
            print(f"{pkg} -> {', '.join(deps)}")

def validate_arguments(args):
    """Валидация аргументов"""
    errors = []
    
    if args.mode == 'test' and not os.path.exists(args.repo_url):
        errors.append(f"Ошибка: Тестовый файл не найден: {args.repo_url}")
    
    if not args.mode == 'test' and not args.version:
        errors.append("Ошибка: Для реального режима требуется указать --version")
    
    return errors

def main():
    parser = argparse.ArgumentParser(
        description='Построение графа зависимостей пакетов',
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False
    )
    
    # Обработка справки
    if '-h' in sys.argv or '--help' in sys.argv:
        print("Использование: app.py --package_name <имя> --repo_url <url/путь> [--version <версия>] --mode <режим> [--filter_substring <подстрока>]")
        print("\nОбязательные параметры:")
        print("  --package_name <имя>          Имя корневого пакета")
        print("  --repo_url <url/путь>         URL репозитория или путь к файлу")
        print("  --mode <режим>                Режим работы:\n"
              "                                  download - реальный репозиторий\n"
              "                                  test - тестовый файл с графом")
        print("\nДополнительные параметры:")
        print("  --version <версия>            Версия пакета (только для реального режима)")
        print("  --filter_substring <строка>   Исключить пакеты, содержащие подстроку")
        print("  -h, --help                    Показать справку")
        sys.exit(0)
    
    # Аргументы
    parser.add_argument('--package_name', type=str, required=True)
    parser.add_argument('--repo_url', type=str, required=True)
    parser.add_argument('--mode', type=str, choices=['download', 'test'], required=True)
    parser.add_argument('--version', type=str)
    parser.add_argument('--filter_substring', type=str, default='')
    
    # Парсинг
    try:
        args = parser.parse_args()
    except SystemExit:
        parser.print_help()
        sys.exit(1)
    
    # Валидация
    errors = validate_arguments(args)
    if errors:
        print("\nОШИБКИ В ПАРАМЕТРАХ:")
        for error in errors:
            print(f"- {error}")
        sys.exit(1)
    
    try:
        # Загрузка данных в зависимости от режима
        if args.mode == 'test':
            print(f"[+] Загрузка тестового графа из: {args.repo_url}")
            package_graph = load_test_graph(args.repo_url)
            root_package = args.package_name.upper()
        else:
            print(f"[+] Загрузка данных из: {args.repo_url}")
            packages_data = fetch_packages_data(args.repo_url)
            packages_index = parse_packages_index(packages_data)
            
            # Поиск пакета
            pkg_key = f"{args.package_name}:amd64"
            if pkg_key not in packages_index and args.package_name in packages_index:
                pkg_key = args.package_name
            
            if pkg_key not in packages_index:
                raise ValueError(f"Пакет '{args.package_name}' не найден в репозитории")
            
            package_info = packages_index[pkg_key]
            if args.version and package_info['Version'] != args.version:
                raise ValueError(f"Версия '{args.version}' не найдена. Доступна: {package_info['Version']}")
            
            # Построение графа зависимостей
            package_graph = {}
            direct_deps = extract_direct_dependencies(package_info.get('Depends', ''))
            package_graph[args.package_name] = direct_deps
            
            root_package = args.package_name
        
        # Построение полного графа с DFS
        print(f"[+] Построение графа зависимостей для {root_package}")
        full_graph = dfs_build_graph(
            root_package,
            package_graph,
            args.filter_substring
        )
        
        # Вывод результата
        print_dependency_graph(full_graph, root_package)
        print(f"\nГраф успешно построен! Всего узлов: {len(full_graph)}")
    
    except Exception as e:
        print(f"\nКРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
