import glob
import os
import sys
from enum import Enum
from parse import compile
from pathlib import Path


entry_points = [ 'vaos-entry.jsx', 'services/mocks/index.js' ]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


class SourceType(Enum):
    JS = 1
    JSX = 2
    JSON = 3
    UNIT = 4
    E2E = 5
    TYPES = 6
    UNKNOWN = 7


class Import:
    def __init__(self, source_path, line, line_num):
        self.source_path = source_path
        self.line = line
        self.line_num = line_num

    def __str__(self):
        return f"{self.line_num}: {self.line}"


class LocalImport(Import):
    def __init__(self, source_path, line, line_num, module, imports, import_all):
        super().__init__(source_path, line, line_num)
        self.module = module
        self.module_path = Path.joinpath(Path(source_path).parent, module).resolve()
        self.imports = imports
        self.import_all = import_all


class Export:
    def __init__(self, name, line_num):
        self.name = name
        self.line_num = line_num
        self.references = 0

    def __str__(self):
        return f"{self.line_num}: {self.name}"


class Source:
    # Import formats
    import_default_and_named = compile("import {default}, {{{named}}} from '{module}';")
    import_named = compile("import {{{named}}} from '{module}';")
    import_default = compile("import {default} from '{module}';")
    import_dynamic = compile("import(/* webpackChunkName: {chunk_name} */ '{module}').then(({{{named}}}) => {var}")
    import_file = compile("import '{file}';")
    require_all = compile("const {all} = require('{module}');")
    require_all_comment = compile("// const {all} = require('{module}');")
    require_named = compile("const {{{named}}} = require('{module}');")

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
    module_exports_list = compile("module.exports = [{exports}];")
    module_exports_object = compile("module.exports = {{{exports}}};")

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
            self.path_for_import = path

        self.exports = {}
        self.imports = []
        self.__resolve_definitions()

    def __split_by_comma(self, values):
        values = values.split(',')
        return [v.strip() for v in values if v.strip()]

    def __resolve_import(self, line, line_num):
        for import_type in [
            Source.import_default_and_named,
            Source.import_named,
            Source.import_default,
            Source.import_dynamic,
            Source.require_all,
            Source.require_all_comment,
            Source.require_named,
        ]:
            if result := import_type.search(line):
                if result['module'].startswith('.'):
                    imports = []
                    if 'default' in result:
                        imports.append('default')
                    if 'named' in result:
                        imports.extend(self.__split_by_comma(result['named']))
                    self.imports.append(LocalImport(self.path, line, line_num, result['module'], imports, 'all' in result))
                else:
                    self.imports.append(Import(self.path, line, line_num))
                return

        if result := Source.import_file.search(line):
            self.imports.append(Import(self.path, line, line_num))
            return

        eprint(f"Found unexpected import: {line} in file {self.path}:{line_num}")

    def __add_export(self, line_num, export_name):
        export = Export(export_name, line_num)
        self.exports[export.name] = export

    def __resolve_export(self, export, line_num):
        if result := Source.multiple_export.search(export):
            for name in self.__split_by_comma(result['exports']):
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
            Source.module_exports_list,
        ]:
            if result := export_type.search(export):
                self.__add_export(line_num, result['name'] if 'name' in result else 'default')
                return

        if result := Source.module_exports_object.search(export):
            for name in self.__split_by_comma(result['exports']):
                self.__add_export(line_num, name)
            return

        eprint(f"Found unexpected export: {export} in file {self.path}:{line_num}")

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
                    line, lines = self.__read_until(file, ';', strip_line)
                    line_num += lines
                    self.__resolve_import(line, line_num)
                if 'require(' in strip_line:
                    line, lines = self.__read_until(file, ';', strip_line)
                    line_num += lines
                    self.__resolve_import(line, line_num)
                elif strip_line.startswith('export'):
                    if 'connect' in strip_line:
                        export, lines = self.__read_until(file, ';', strip_line)
                        line_num += lines
                        self.__resolve_export(export, line_num)
                    else:
                        self.__resolve_export(line, line_num)
                elif strip_line.startswith('module.exports'):
                    if '[' in strip_line:
                        export, lines = self.__read_until(file, ']', strip_line)
                        line_num += lines
                        self.__resolve_export(export, line_num)
                    elif '{' in strip_line:
                        export, lines = self.__read_until(file, ';', strip_line)
                        line_num += lines
                        self.__resolve_export(export, line_num)


def parse(dir):
    sources = []
    files_include = glob.glob(dir + '/**/*.js', recursive=True)
    files_include.extend(glob.glob(dir + '/**/*.jsx', recursive=True))
    files_include.extend(glob.glob(dir + '/**/*.json', recursive=True))
    files_exclude = glob.glob(dir + '/lib/**/*.js', recursive=True)
    files_exclude.extend(glob.glob(dir + '/node_modules/**/*.js', recursive=True))
    files_exclude.extend(glob.glob(dir + '/node_modules/**/*.jsx', recursive=True))
    files_exclude.extend(glob.glob(dir + '/node_modules/**/*.json', recursive=True))

    for file in set(files_include) - set(files_exclude):
        sources.append(Source(file))

    return sorted(sources, key=lambda x: x.path)


def orphans(dir):
    print(f"Inspecting: {dir}")
    sources = parse(dir)

    print(f"Found {len(sources)} source files")
    for source in sources:
        print(f"{source.path}")
        if source.path_for_import:
            print(f"  Importable at: {source.path_for_import}")

        local_imports = []
        library_imports = []
        for imp in source.imports:
            if isinstance(imp, LocalImport):
                local_imports.append(imp)
            else:
                library_imports.append(imp)

        print(f"  Library imports: {len(library_imports)}")
        for imp in library_imports:
            print(f"    {imp}")
        print(f"  Local imports: {len(local_imports)}")
        for imp in local_imports:
            print(f"    {'*' if imp.import_all else ''}{imp}")
        print(f"  Exports: {len(source.exports)}")
        for export in source.exports.values():
            print(f"    {export}")

    for source in sources:
        # Ensure file type recognized
        if source.type == SourceType.UNKNOWN:
            eprint(f"Unknown file type: {source.path}")
            continue
        entry_paths = [ os.path.join(dir, entry_point) for entry_point in entry_points ]
        # Check for expected exports
        if (source.type in [ SourceType.JS, SourceType.JSX, SourceType.JSON ]
            and len(source.exports) == 0
            and source.path not in entry_paths):
            eprint(f"Source file {source.path} has no exports")
        # Check for unexpected exports
        if source.type in [ SourceType.UNIT, SourceType.E2E ] and len(source.exports) > 0:
            eprint(f"Test file {source.path} has exports")


if __name__ == "__main__":
    orphans(sys.argv[1])