import glob
import sys
from enum import Enum
from parse import compile

class SourceType(Enum):
    JS = 1
    JSX = 2
    JSON = 3
    UNIT = 4
    E2E = 5
    TYPES = 6
    UNKNOWN = 7

class Export:
    def __init__(self, name, line_num):
        self.name = name
        self.line_num = line_num
        self.references = 0

    def __str__(self):
        return f"{self.name} - line: {self.line_num}"


class Source:
    # Export formats
    multiple_export = compile("export {{{exports}}};")
    export_const = compile("export const {name} ")
    export_function = compile("export function {name}(")
    export_async_function = compile("export async function {name}(")
    export_class = compile("export class {name} ")
    export_default_function = compile("export default function {function_name}(")
    export_default_class = compile("export default class {class_name} ")
    export_default_connect = compile("export default connect({maps})({component});")
    export_default_value = compile("export default {value_name};")
    export_default_object = compile("export default {")

    # Import formats

    def __init__(self, path):
        self.path = path

        self.type = SourceType.UNKNOWN
        if path.endswith('.unit.spec.jsx'):
            self.type = SourceType.UNIT
        elif path.endswith('.cypress.spec.js'):
            self.type = SourceType.E2E
        elif path.endswith('/types.js'):
            self.type = SourceType.TYPES
        elif path.endswith('.js'):
            self.type = SourceType.JS
        elif path.endswith('.jsx'):
            self.type = SourceType.JSX
        elif path.endswith('.json'):
            self.type = SourceType.JSON

        self.path_for_import = None
        if self.type == SourceType.JS:
            self.path_for_import = path[:-3]
        elif self.type == SourceType.JSX:
            self.path_for_import = path[:-4]
        elif self.type == SourceType.JSON:
            self.path_for_import = path[:-5]

        self.exports = {}
        self.default = None
        self.imports = []
        self.__resolve_definitions()

    def __resolve_import(self, import_):
        self.imports.append(import_)

    def __add_export(self, line_num, export_name):
        export = Export(export_name, line_num)
        self.exports[export.name] = export

    def __resolve_export(self, export, line_num):
        for export_type in [
            Source.multiple_export,
            # Source.multiple_export_default,
        ]:
            if result := export_type.search(export):
                for name in result['exports'].split(','):
                    self.__add_export(line_num, name)
                return

        for export_type in [
            Source.export_const,
            Source.export_function,
            Source.export_async_function,
            Source.export_class,
            Source.export_default_function,
            Source.export_default_class,
            Source.export_default_connect,
            Source.export_default_value,
            Source.export_default_object,
        ]:
            if result := export_type.search(export):
                self.__add_export(line_num, result['name'] if 'name' in result else 'default')
                return

        print(f"Found unexpected export: {export} in file {self.path}:{line_num}")

    def __read_until(self, file, char, initial_line):
        count = 0
        result = initial_line
        while char not in result:
            result += file.readline().strip()
            count += 1
        return result, count

    def __resolve_definitions(self):
        if self.type == SourceType.JSON:
            self.__add_export(0, 'default')
            return

        line_num = 0
        with open(self.path) as file:
            while (line := file.readline()):
                line_num += 1
                strip_line = line.strip()
                if strip_line.startswith('import'):
                    import_, lines = self.__read_until(file, ';', strip_line)
                    line_num += lines
                    self.__resolve_import(import_)
                elif strip_line.startswith('export'):
                    if 'connect' in strip_line:
                        export, lines = self.__read_until(file, ';', strip_line)
                        self.__resolve_export(export, line_num)
                    else:
                        self.__resolve_export(line, line_num)


def parse(dir):
    sources = []
    files_include = glob.glob(dir + '/**/*.js', recursive=True)
    files_include.extend(glob.glob(dir + '/**/*.jsx', recursive=True))
    files_include.extend(glob.glob(dir + '/**/*.json', recursive=True))
    files_exclude = glob.glob(dir + '/node_modules/**/*.js', recursive=True)
    files_exclude.extend(glob.glob(dir + '/node_modules/**/*.jsx', recursive=True))
    files_exclude.extend(glob.glob(dir + '/node_modules/**/*.json', recursive=True))

    for file in set(files_include) - set(files_exclude):
        sources.append(Source(file))

    return sorted(sources, key=lambda x: x.path)

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def orphans(dir):
    print(f"Inspecting: {dir}")
    sources = parse(dir)

    print(f"Found {len(sources)} source files")
    for source in sources:
        print(f"{source.path}")
        if source.path_for_import:
            print(f"  Importable at: {source.path_for_import}")
        print("  Imports:")
        for imp in source.imports:
            print(f"    {imp}")
        print(f"  Exports: {len(source.exports)}")
        for export in source.exports.values():
            print(f"    {export}")

    for source in sources:
        # Ensure file type recognized
        if source.type == SourceType.UNKNOWN:
            eprint(f"Unknown file type: {source.path}")
            continue
        # Check for expected exports
        if source.type in [ SourceType.JS, SourceType.JSX, SourceType.JSON ]:
            if len(source.exports) == 0:
                eprint(f"Source file {source.path} has no exports")
        # Check for unexpected exports
        if source.type in [ SourceType.UNIT, SourceType.E2E ]:
            if len(source.exports) > 0:
                eprint(f"Test file {source.path} has exports")


if __name__ == "__main__":
    orphans(sys.argv[1])