import glob
import os
import sys
from enum import Enum
from parse import compile
from pathlib import Path


# These are the entry points to the applications and must not be removed even if unreferenced by other files
entry_points = [ 'vaos-entry.jsx', 'services/mocks/index.js' ]


# Print to stderr
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


# Abstraction for library and local imports
class Import:
    def __init__(self, source_path, line, line_num):
        self.source_path = source_path
        self.line = line
        self.line_num = line_num

    def __str__(self):
        return f"{self.line_num}: {self.line}"


# Abstraction for local imports
class LocalImport(Import):
    def __init__(self, source_path, line, line_num, module, imports, import_all):
        super().__init__(source_path, line, line_num)
        # parsed module of the import e.g. '../relative/path/to/import/module'
        self.module = module
        # resolved absolute path to the imported module
        self.module_path = str(Path.joinpath(Path(source_path).parent, module).resolve())
        # list of imports (including default) from the module
        self.imports = imports
        # flag for importing all exports of a module (e.g. for import * or require imports)
        self.import_all = import_all


# Abstraction for exports
class Export:
    def __init__(self, name, line_num):
        self.name = name
        self.line_num = line_num
        # counting number of times the export was imported by other files
        self.references = 0

    def __str__(self):
        return f"{self.line_num}: {self.name}"


class Source:
    # Import formats
    import_star = compile("import * as {all} from '{module}';")
    import_default_and_named = compile("import {default}, {{{named}}} from '{module}';")
    import_named = compile("import {{{named}}} from '{module}';")
    import_default = compile("import {default} from '{module}';")
    import_dynamic = compile("import(/* webpackChunkName: {chunk_name} */ '{module}').then(({{{named}}}) => {var}")
    import_file = compile("import '{file}';")
    require_all = compile("const {all} = require('{module}');")
    require_all_comment = compile("// const {all} = require('{module}');")
    require_named = compile("const {{{named}}} = require('{module}');")
    import_alias = compile("{named} as {alias}")

    # Export formats
    multiple_export = compile("export {{{exports}}};")
    multiple_export_const = compile("export const {{{exports}}} =")
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

    def __init__(self, path: str):
        self.path = path

        self.type = SourceType.UNKNOWN
        self.paths_for_import = []
        self.unit_path = ""
        if path.endswith('.unit.spec.jsx'):
            self.type = SourceType.UNIT
        elif path.endswith('.cypress.spec.js'):
            self.type = SourceType.E2E
        elif path.endswith('/types.js'):
            self.type = SourceType.TYPES
        elif path.endswith('.js'):
            self.type = SourceType.JS
            self.paths_for_import.append(path[:-3])
            self.unit_path = f"{path[:-3]}.unit.spec.jsx"
            # Adding additional import path for index.js sources
            if path.endswith('/index.js'):
                self.paths_for_import.append(path[:-9])
        elif path.endswith('.jsx'):
            self.type = SourceType.JSX
            self.paths_for_import.append(path[:-4])
            self.unit_path = f"{path[:-4]}.unit.spec.jsx"
            # Adding additional import path for index.jsx sources
            if path.endswith('/index.jsx'):
                self.paths_for_import.append(path[:-10])
        elif path.endswith('.json'):
            self.type = SourceType.JSON
            self.paths_for_import.append(path)

        self.exports: dict[str, Export] = {}
        self.local_imports: list[LocalImport] = []
        self.library_imports: list[Import] = []
        self.__resolve_definitions()

    # Split by comma and remove empty entries
    def __split_by_comma(self, values):
        values = values.split(',')
        return [v.strip() for v in values if v.strip()]

    def __resolve_import(self, line, line_num):
        for import_type in [
            Source.import_star,
            Source.import_default_and_named,
            Source.import_named,
            Source.import_default,
            Source.import_dynamic,
            Source.require_all,
            Source.require_all_comment,
            Source.require_named,
        ]:
            if result := import_type.search(line):
                # Local imports, exclude imports of lib/moment-tz.js
                if result['module'].startswith('.') and not result['module'].endswith('moment-tz'):
                    imports = []
                    if 'default' in result:
                        imports.append('default')
                    if 'named' in result:
                        for named in self.__split_by_comma(result['named']):
                            if alias_result := Source.import_alias.search(named):
                                imports.append(alias_result['named'])
                            else:
                                imports.append(named)
                    self.local_imports.append(LocalImport(self.path, line, line_num, result['module'], imports, 'all' in result))
                else:
                    self.library_imports.append(Import(self.path, line, line_num))
                return

        # exclude file imports (e.g. import './sass/vaos.scss';)
        if result := Source.import_file.search(line):
            self.library_imports.append(Import(self.path, line, line_num))
            return

        eprint(f"Found unexpected import: {line} in file {self.path}:{line_num}")

    def __add_export(self, line_num, export_name):
        export = Export(export_name, line_num)
        self.exports[export.name] = export

    def __resolve_export(self, export, line_num):
        for export_type in [
            Source.multiple_export,
            Source.multiple_export_const,
        ]:
            if result := export_type.search(export):
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

    # Read until the expected token is added to the result
    def __read_until(self, file, token, initial_line):
        count = 0
        result = initial_line
        while token not in result:
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
                # ES module imports
                if strip_line.startswith('import'):
                    line, lines = self.__read_until(file, ';', strip_line)
                    line_num += lines
                    self.__resolve_import(line, line_num)
                # CommonJS imports
                if 'require(' in strip_line:
                    line, lines = self.__read_until(file, ';', strip_line)
                    line_num += lines
                    self.__resolve_import(line, line_num)
                # ES exports
                elif strip_line.startswith('export'):
                    if 'connect' in strip_line:
                        export, lines = self.__read_until(file, ';', strip_line)
                        line_num += lines
                        self.__resolve_export(export, line_num)
                    else:
                        self.__resolve_export(line, line_num)
                #  CommonJS exports
                elif strip_line.startswith('module.exports'):
                    if '[' in strip_line:
                        export, lines = self.__read_until(file, ']', strip_line)
                        line_num += lines
                        self.__resolve_export(export, line_num)
                    elif '{' in strip_line:
                        export, lines = self.__read_until(file, ';', strip_line)
                        line_num += lines
                        self.__resolve_export(export, line_num)


# Abstraction sources that compose an application
class Application:
    def __init__(self, sources: list[Source]):
        self.sources = sources
        self.modules: dict[str, Source] = {}

    def resolve_references(self):
        # Create dictionary of modules using their import path(s)
        for source in self.sources:
            if source.type in [ SourceType.JS, SourceType.JSX, SourceType.JSON ]:
                for path in source.paths_for_import:
                    if path in self.modules:
                        eprint(f"Duplicate import path: {path} for {source.path} and {self.modules[path].path}")
                    self.modules[path] = source

        # Count number of references for each export via imports from other files
        for source in self.sources:
            for local_import in source.local_imports:
                if local_import.module_path in self.modules:
                    module = self.modules[local_import.module_path]
                    # ignore imports in unit tests from their component, otherwise components with tests will never be removed
                    if source.type == SourceType.UNIT and source.path == module.unit_path:
                        continue
                    if local_import.import_all:
                        for export in module.exports.values():
                            export.references += 1
                    else:
                        for import_name in local_import.imports:
                            if import_name in module.exports:
                                module.exports[import_name].references += 1
                            else:
                                eprint(f"Import {import_name} of {local_import.module_path} from {source.path}:{local_import.line_num} cannot found")
                else:
                    eprint(f"Module {local_import.module_path} from {source.path}:{local_import.line_num} cannot be found")


# Parse all files in the directory into Sources
def parse(dir) -> list[Source]:
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


# Diagnostics for all sources
def inspect_sources(sources: list[Source]):
    for source in sources:
        print(f"{source.path}")
        if source.paths_for_import:
            print(f"  Importable at: {source.paths_for_import}")
        print(f"  Library imports: {len(source.library_imports)}")
        for imp in source.library_imports:
            print(f"    {imp}")
        print(f"  Local imports: {len(source.local_imports)}")
        for imp in source.local_imports:
            print(f"    {'*' if imp.import_all else ''}{imp}")
        print(f"  Exports: {len(source.exports)}")
        for export in source.exports.values():
            print(f"    {export} used {export.references} times")


def analyze(dir):
    print(f"Inspecting: {dir}")
    sources = parse(dir)

    print(f"Analyzing {len(sources)} source files")

    app = Application(sources)
    app.resolve_references()

    inspect_sources(app.sources)

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
    analyze(sys.argv[1])