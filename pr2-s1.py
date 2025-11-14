# -*- coding: utf-8 -*-
import argparse
import sys
import urllib.request
import gzip
import bz2
import os
import re
import subprocess
import json
import tempfile
from collections import deque

def fetch_packages_data(repo_url):
    """Загрузка данных репозитория"""
    try:
        if repo_url.startswith(('http://', 'https://')):
            headers = {'User-Agent': 'Mozilla/5.0 (Ubuntu) apt/2.4.9'}
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

def dfs_build_graph(package, graph, filter_substring, visited=None, current_path=None, result=None, cycles_found=None):
    """Построение графа зависимостей с DFS и обнаружением циклов"""
    if visited is None:
        visited = set()
    if current_path is None:
        current_path = []
    if result is None:
        result = {}
    if cycles_found is None:
        cycles_found = []
    
    # Фильтрация по подстроке
    if filter_substring and filter_substring.lower() in package.lower():
        return result
    
    # Проверка цикла
    if package in current_path:
        cycle_path = ' -> '.join(current_path + [package])
        # Вместо исключения - сохраняем информацию о цикле и продолжаем
        if cycle_path not in cycles_found:
            cycles_found.append(cycle_path)
        return result
    
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
        dfs_build_graph(dep, graph, filter_substring, visited, current_path, result, cycles_found)
        # Добавление ребра в граф
        if not (filter_substring and filter_substring.lower() in dep.lower()):
            result[package].append(dep)
    
    current_path.pop()
    return result, cycles_found

def topological_sort(graph, start_node, filter_substring):
    """Топологическая сортировка для определения порядка установки"""
    in_degree = {}
    for node in graph:
        in_degree[node] = 0
    
    # Вычисление степеней захода
    for node, deps in graph.items():
        for dep in deps:
            if dep in in_degree:
                in_degree[dep] += 1
            else:
                in_degree[dep] = 1
    
    # Очередь для Kahn's algorithm
    queue = deque()
    if start_node in in_degree and in_degree[start_node] == 0:
        queue.append(start_node)
    
    # Фильтрация начального узла
    if filter_substring and filter_substring.lower() in start_node.lower():
        return []
    
    # BFS для топологической сортировки
    result = []
    while queue:
        node = queue.popleft()
        result.append(node)
        
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                if not (filter_substring and filter_substring.lower() in neighbor.lower()):
                    queue.append(neighbor)
    
    return result

def generate_dot_graph(graph, root_package, filter_substring="", package_versions=None):
    """Генерация DOT-кода для Graphviz с улучшенной визуализацией"""
    dot_lines = []
    dot_lines.append("digraph G {")
    dot_lines.append("  rankdir=TB;")
    dot_lines.append("  node [shape=box, style=filled, fontname=Arial, fontsize=12];")
    dot_lines.append('  graph [label="Граф зависимостей пакета \\"' + root_package + '\\"", labelloc=t, fontsize=16, fontname=Arial];')
    
    # Сбор всех узлов
    all_nodes = set()
    for node, deps in graph.items():
        all_nodes.add(node)
        all_nodes.update(deps)
    
    # Формирование узлов с цветовой дифференциацией
    for node in all_nodes:
        color = "#E8F4E8"  # Светло-зеленый для корневого
        style = "filled,bold"
        tooltip = node
        
        if node == root_package:
            color = "#D5E8D4"
        elif filter_substring and filter_substring.lower() in node.lower():
            color = "#F8CECC"  # Светло-красный для отфильтрованных
            tooltip += " (отфильтрован)"
        else:
            color = "#DAE8FC"  # Светло-голубой для зависимостей
        
        # Добавление версии в подсказку
        if package_versions and node in package_versions:
            tooltip += f"\\nВерсия: {package_versions[node]}"
        
        dot_lines.append(f'  "{node}" [fillcolor="{color}", penwidth=1.5, tooltip="{tooltip}", label="{node}"];')
    
    # Формирование ребер
    for node, deps in graph.items():
        for dep in deps:
            edge_style = "solid"
            edge_color = "#333333"
            
            if filter_substring and (filter_substring.lower() in node.lower() or filter_substring.lower() in dep.lower()):
                edge_style = "dashed"
                edge_color = "#CC0000"
            
            dot_lines.append(f'  "{node}" -> "{dep}" [style={edge_style}, color="{edge_color}", arrowsize=0.8];')
    
    # Добавление легенды
    dot_lines.append('')
    dot_lines.append('  // Легенда')
    dot_lines.append('  subgraph cluster_legend {')
    dot_lines.append('    label="Легенда";')
    dot_lines.append('    fontsize=14;')
    dot_lines.append('    style=rounded;')
    dot_lines.append('    color=gray;')
    dot_lines.append('    node [shape=box, style=filled];')
    dot_lines.append('    ')
    dot_lines.append('    legend_root [label="Корневой пакет", fillcolor="#D5E8D4"];')
    dot_lines.append('    legend_dep [label="Зависимость", fillcolor="#DAE8FC"];')
    if filter_substring:
        dot_lines.append('    legend_filtered [label="Отфильтрован", fillcolor="#F8CECC"];')
    dot_lines.append('  }')
    
    dot_lines.append("}")
    return "\n".join(dot_lines)

def visualize_with_graphviz(dot_code, output_filename="dependency_graph"):
    """Визуализация графа с помощью Graphviz"""
    try:
        # Проверка наличия Graphviz
        subprocess.run(["dot", "-V"], capture_output=True, check=True)
        
        # Создание временного DOT-файла
        with tempfile.NamedTemporaryFile(suffix=".dot", delete=False, mode='w', encoding='utf-8') as tmpfile:
            tmpfile.write(dot_code)
            dot_path = tmpfile.name
        
        # Генерация PNG
        png_path = output_filename + ".png"
        result = subprocess.run(
            ["dot", "-Tpng", dot_path, "-o", png_path],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Ошибка генерации изображения: {result.stderr}")
        
        # Удаление временного файла
        os.unlink(dot_path)
        
        # Автоматическое открытие изображения
        print(f"\n[+] Граф визуализирован и сохранен в: {png_path}")
        try:
            if sys.platform.startswith('darwin'):
                subprocess.run(["open", png_path])
            elif sys.platform.startswith('win'):
                os.startfile(png_path)
            elif sys.platform.startswith('linux'):
                subprocess.run(["xdg-open", png_path])
        except Exception as e:
            print(f"[i] Не удалось автоматически открыть изображение. Откройте файл вручную: {png_path}")
        
        return True
    
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"\n!!! Graphviz не установлен или недоступен: {str(e)}")
        print("Сохраняю DOT-файл для ручной визуализации...")
        dot_filename = output_filename + ".dot"
        with open(dot_filename, 'w', encoding='utf-8') as f:
            f.write(dot_code)
        print(f"[+] DOT-файл сохранен: {dot_filename}")
        print(f"[i] Для визуализации выполните: dot -Tpng {dot_filename} -o {output_filename}.png")
        return False

def print_dependency_graph(graph, root_package, show_install_order=False, filter_substring="", package_versions=None, visualize=False):
    """Вывод графа зависимостей и визуализация"""
    # Вывод структуры графа
    print(f"\nГРАФ ЗАВИСИМОСТЕЙ ДЛЯ {root_package}:")
    visited = set()
    stack = [(root_package, 0)]
    
    while stack:
        pkg, level = stack.pop()
        if pkg in visited:
            continue
        visited.add(pkg)
        
        indent = "  " * level + ("└── " if level > 0 else "")
        version_info = ""
        if package_versions and pkg in package_versions:
            version_info = f" (v{package_versions[pkg]})"
        print(f"{indent}{pkg}{version_info}")
        
        # Добавляем зависимости в обратном порядке для правильного отображения
        for dep in reversed(graph.get(pkg, [])):
            if dep not in visited:
                stack.append((dep, level + 1))
    
    # Вывод порядка установки
    if show_install_order:
        install_order = topological_sort(graph, root_package, filter_substring)
        
        print("\nПОРЯДОК УСТАНОВКИ ЗАВИСИМОСТЕЙ:")
        if install_order:
            for i, pkg in enumerate(install_order, 1):
                version_info = f" (v{package_versions[pkg]})" if package_versions and pkg in package_versions else ""
                print(f"{i}. {pkg}{version_info}")
        else:
            print("Порядок установки не может быть определен")
    
    # Визуализация графа
    if visualize:
        dot_code = generate_dot_graph(graph, root_package, filter_substring, package_versions)
        visualize_with_graphviz(dot_code, f"graph_{root_package}")

def validate_arguments(args):
    """Валидация аргументов"""
    errors = []
    
    if args.mode == 'test' and not os.path.exists(args.repo_url):
        errors.append(f"Ошибка: Тестовый файл не найден: {args.repo_url}")
    
    # Версия опциональна - будет использована доступная версия из репозитория
    
    return errors

def main():
    parser = argparse.ArgumentParser(
        description='Визуализация графа зависимостей пакетов',
        formatter_class=argparse.RawTextHelpFormatter,
        add_help=False
    )
    
    # Обработка справки
    if '-h' in sys.argv or '--help' in sys.argv:
        print("Использование: app.py --package_name <имя> --repo_url <url/путь> --mode <режим> [--version <версия>] [--filter_substring <подстрока>] [--show_install_order] [--visualize]")
        print("\nОбязательные параметры:")
        print("  --package_name <имя>          Имя корневого пакета")
        print("  --repo_url <url/путь>         URL репозитория или путь к файлу")
        print("  --mode <режим>                Режим работы:\n"
              "                                  download - реальный репозиторий\n"
              "                                  test - тестовый файл с графом")
        print("\nДополнительные параметры:")
        print("  --version <версия>            Версия пакета (опционально, для проверки)")
        print("  --filter_substring <строка>   Исключить пакеты, содержащие подстроку")
        print("  --show_install_order          Показать порядок установки зависимостей")
        print("  --visualize                   Визуализировать граф через Graphviz")
        print("  -h, --help                    Показать справку")
        sys.exit(0)
    
    # Аргументы
    parser.add_argument('--package_name', type=str, required=True)
    parser.add_argument('--repo_url', type=str, required=True)
    parser.add_argument('--mode', type=str, choices=['download', 'test'], required=True)
    parser.add_argument('--version', type=str)
    parser.add_argument('--filter_substring', type=str, default='')
    parser.add_argument('--show_install_order', action='store_true')
    parser.add_argument('--visualize', action='store_true')
    
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
        package_versions = {}
        
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
            
            # Проверка версии (если указана)
            if args.version and package_info['Version'] != args.version:
                raise ValueError(f"Версия '{args.version}' не найдена. Доступна: {package_info['Version']}")
            
            # Сохранение версий для отображения
            package_versions[args.package_name] = package_info['Version']
            
            # Построение графа зависимостей (рекурсивно для всех зависимостей)
            package_graph = {}
            
            def build_package_graph_recursive(pkg_name, visited=None):
                """Рекурсивно строит граф зависимостей для режима download"""
                if visited is None:
                    visited = set()
                
                # Избегаем повторной обработки
                if pkg_name in visited:
                    return
                visited.add(pkg_name)
                
                # Поиск пакета в индексе
                pkg_key = f"{pkg_name}:amd64"
                if pkg_key not in packages_index:
                    # Попробуем без архитектуры
                    pkg_key = pkg_name
                    if pkg_key not in packages_index:
                        # Пакет не найден, пропускаем
                        return
                
                pkg_info = packages_index[pkg_key]
                
                # Сохранение версии
                if pkg_name not in package_versions:
                    package_versions[pkg_name] = pkg_info.get('Version', 'unknown')
                
                # Извлечение зависимостей
                direct_deps = extract_direct_dependencies(pkg_info.get('Depends', ''))
                package_graph[pkg_name] = direct_deps
                
                # Рекурсивная обработка каждой зависимости
                for dep in direct_deps:
                    build_package_graph_recursive(dep, visited)
            
            # Запуск рекурсивного построения графа
            build_package_graph_recursive(args.package_name)
            
            root_package = args.package_name
        
        # Построение полного графа с DFS
        print(f"[+] Построение графа зависимостей для {root_package}")
        full_graph, cycles_found = dfs_build_graph(
            root_package,
            package_graph,
            args.filter_substring
        )
        
        # Вывод информации о циклах (если найдены)
        if cycles_found:
            print(f"\n⚠️  ОБНАРУЖЕНО ЦИКЛИЧЕСКИХ ЗАВИСИМОСТЕЙ: {len(cycles_found)}")
            for i, cycle in enumerate(cycles_found, 1):
                print(f"  {i}. {cycle}")
        
        # Вывод результата с визуализацией
        print_dependency_graph(
            full_graph, 
            root_package, 
            args.show_install_order, 
            args.filter_substring,
            package_versions,
            args.visualize
        )
        
        print(f"\nГраф успешно построен! Всего узлов: {len(full_graph)}")
        
        # Сравнение с штатными инструментами
        if not args.mode == 'test' and args.visualize:
            print("\nСРАВНЕНИЕ С ШТАТНЫМИ ИНСТРУМЕНТАМИ (apt-rdepends):")
            print("1. apt-rdepends включает рекомендуемые (Recommends) и предложенные (Suggests) зависимости")
            print("2. Наш алгоритм учитывает только обязательные зависимости (Depends)")
            print("3. apt-rdepends разрешает альтернативные зависимости динамически")
            print("4. Визуализация apt-rdepends не поддерживает фильтрацию по подстрокам")
            print("5. Наш алгоритм обнаруживает циклы и корректно их обрабатывает (продолжает работу)")
            if cycles_found:
                print(f"   → Обнаружено циклов: {len(cycles_found)}")
                print("   → apt-rdepends может зависнуть на циклических зависимостях")
    
    except Exception as e:
        print(f"\nКРИТИЧЕСКАЯ ОШИБКА: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
