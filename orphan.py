import glob
from parse import compile
import sys

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
    multiple_export_default = compile("export default {{{exports}}};")
    export_const = compile("export const {name} ")
    export_function = compile("export function {name}(")
    export_async_function = compile("export async function {name}(")
    export_class = compile("export class {name} ")
    export_default_function = compile("export default function {name}(")
    export_default_class = compile("export default class {name} ")
    export_default_value = compile("export default {name};")
    export_default_object = compile("export default {")

    # Import formats

    def __init__(self, path):
        self.path = path
        self.exports = {}
        self.default = None
        self.imports = []
        self.__resolve_definitions()

    def __resolve_import(self, import_, line_num):
        self.imports.append(import_)

    def __add_export(self, line_num, export_name):
        export = Export(export_name, line_num)
        self.exports[export.name] = export

    def __resolve_export(self, export, line_num):
        for export_type in [
            Source.multiple_export,
            Source.multiple_export_default,
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
            Source.export_default_value,
        ]:
            if result := export_type.search(export):
                self.__add_export(line_num, result['name'])
                return

        if result := Source.export_default_object.search(export):
                self.__add_export(line_num, 'default')
                return

        print(f"Found unusual export: {export} in file {self.path}:{line_num}")

    def __resolve_definitions(self):
        line_num = 0
        with open(self.path) as file:
            while (line := file.readline()):
                line_num += 1
                strip_line = line.strip()
                if strip_line.startswith('import'):
                    import_ = strip_line
                    while ';' not in import_:
                        import_ += file.readline().strip()
                        line_num += 1
                    self.__resolve_import(import_, line_num)
                elif strip_line.startswith('export'):
                    if 'connect' in strip_line:
                        export = strip_line
                        while ';' not in export:
                            export += file.readline().strip()
                            line_num += 1
                        self.__resolve_export(export, line_num)
                    else:
                        self.__resolve_export(line, line_num)


def parse(dir):
    sources = {}
    files_include = glob.glob(dir + '/**/*.js', recursive=True)
    files_include.extend(glob.glob(dir + '/**/*.jsx', recursive=True))
    files_exclude = glob.glob(dir + '/node_modules/**/*.js', recursive=True)
    files_exclude.extend(glob.glob(dir + '/node_modules/**/*.jsx', recursive=True))
    files = set(files_include) - set(files_exclude)
    for file in files:
        source = Source(file)
        sources[file] = source
    return sources

def orphans(dir):
    print(f"Inspecting: {dir}")

    sources = parse(dir)

    print(f"Found {len(sources)} source files")

    for source in sources.values():
        print(f"{source.path}:")
        # print("  Imports:")
        # for imp in source.imports:
        #     print(f"    {imp}")
        print(f"  Exports: {len(source.exports)}")
        for export in source.exports.values():
            print(f"    {export}")


if __name__ == "__main__":
    orphans(sys.argv[1])