import glob
import sys

class SourceFile:
    def __init__(self, path):
        self.path = path
        self.exports = {}
        self.imports = []
        self.__resolve_definitions()

    def __resolve_export(self, export):
        tokens = export.split()
        if 'function' not in tokens:
            raise Exception(f"{self.path} contains an unrecognized export {export}")
        export_function = tokens[tokens.index('function')+1]
        export_function = export_function[:export_function.index('(')]

    def __resolve_definitions(self):
        with open(self.path) as file:
            while (line := file.readline()):
                if 'import' in line:
                    if ';' in line:
                        self.imports.append(line.strip())
                        continue
                    imp = line.strip()
                    while import_line := file.readline():
                        if ';' in import_line:
                            imp += import_line
                            break
                        imp += import_line.strip()
                    self.imports.append(imp.strip())
                elif 'export' in line:
                    if 'function' not in line:
                        print(f"Found unusual export: {line.strip()} in file {self.path}")
                        continue
                    export = self.__resolve_export(line)
                    self.exports[export] = 0


def parse(dir):
    sources = {}
    for file in glob.glob(dir + '/**/*.jsx', recursive=True):
        source = SourceFile(file)
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
        print("  Exports:")
        for exp in source.exports.keys():
            print(f"    {exp}")


if __name__ == "__main__":
    orphans(sys.argv[1])