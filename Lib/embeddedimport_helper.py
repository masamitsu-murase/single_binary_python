"""EmbeddedImporter helper

Implements a PEP 451-compatible path-hook importer backed by the
embedded data exposed from the built-in 'embeddedimport' module.
"""

import _frozen_importlib_external as _bootstrap_external
import _frozen_importlib as _bootstrap
import sys


_c = None
_executable = sys.executable
path_sep = _bootstrap_external.path_sep
alt_path_sep = _bootstrap_external.path_separators[1:]


def _load_c_extension():
    global _c
    if _c is None:
        import embeddedimport
        _c = embeddedimport


def _normalize_line_endings(source: bytes) -> bytes:
    source = source.replace(b"\r\n", b"\n")
    source = source.replace(b"\r", b"\n")
    return source


def _compile_source(pathname: str, source: bytes):
    source = _normalize_line_endings(source)
    return compile(source, pathname, "exec", dont_inherit=True)


def _to_module_path(fullname: str) -> str:
    return fullname.replace(".", "/")


def _normalize_path(path: str) -> str:
    if alt_path_sep:
        path = path.replace(alt_path_sep, path_sep)
    return path


def _to_os_path(executable: str, embedded_path: str) -> str:
    os_embedded_path = embedded_path.replace("/", path_sep)
    return _bootstrap_external._path_join(executable, os_embedded_path)


class EmbeddedImporter(_bootstrap_external._LoaderBasics):
    """PEP 451 path-hook importer for embedded data."""

    def __init__(self, path: str):
        _load_c_extension()

        if not isinstance(path, str):
            raise ImportError("expected str path")

        exe = _executable
        if not exe:
            raise ImportError("sys.executable is not set")

        exe_norm = _normalize_path(exe)
        path_norm = _normalize_path(path)

        if path_norm == exe_norm:
            self.prefix = ""
        elif path_norm.startswith(exe_norm + path_sep):
            rel = path_norm[len(exe_norm) + 1 :]
            rel = rel.replace(path_sep, "/")
            self.prefix = rel + "/" if rel and not rel.endswith("/") else rel
        else:
            raise ImportError("path is not related to executable")

    def _iter_candidates(self, fullname: str):
        modpath = _to_module_path(fullname)
        yield modpath + "/__init__.py", True
        yield modpath + ".py", False
        yield modpath, True

    def _find_entry(self, fullname: str):
        for key, is_package in self._iter_candidates(fullname):
            data_pos = _c._find_entry_in_resource(key)
            if data_pos is not None:
                return key, is_package, True, data_pos
            data_pos = _c._find_entry(key)
            if data_pos is not None:
                return key, is_package, False, data_pos
        return None

    def find_spec(self, fullname: str, target=None):
        modpath = _to_module_path(fullname)
        if not modpath.startswith(self.prefix):
            return None

        info = self._find_entry(fullname)
        if info is None:
            return None

        key, is_package, _, _ = info
        if key.endswith("/__init__.py") or key.endswith(".py"):
            spec = _bootstrap.spec_from_loader(fullname, self, is_package=is_package)
            spec.origin = self.get_filename(fullname)
            return spec

        # Namespace package (no source)
        spec = _bootstrap.ModuleSpec(name=fullname, loader=None, is_package=True)
        path = _to_os_path(_executable, key)
        spec.submodule_search_locations.append(path)
        return spec

    def create_module(self, spec):
        return None

    # Delegate execution to importlib's internal implementation so warning
    # stacklevel attribution matches standard loaders.
    # def exec_module(self, module):
    #     return _bootstrap_external._LoaderBasics.exec_module(self, module)

    def get_code(self, fullname: str):
        info = self._find_entry(fullname)
        if info is None:
            raise ImportError(f"can't find module {fullname!r}")

        key, is_package, use_resource, (offset, size) = info
        data = _c._get_data(offset, size, use_resource=use_resource)
        pathname = _to_os_path(_executable, key)
        return _compile_source(pathname, data)

    def get_source(self, fullname: str):
        info = self._find_entry(fullname)
        if info is None:
            raise ImportError(f"can't find module {fullname!r}")

        key, is_package, use_resource, (offset, size) = info
        data = _c._get_data(offset, size, use_resource=use_resource)
        try:
            return data.decode()
        except UnicodeDecodeError:
            return None

    def get_filename(self, fullname: str):
        info = self._find_entry(fullname)
        if info is None:
            raise ImportError(f"can't find module {fullname!r}")

        key, _, _, _ = info
        return _to_os_path(_executable, key)

    @staticmethod
    def get_data_static(pathname: str):
        if not isinstance(pathname, str):
            raise OSError(0, "", pathname)

        pathname = _normalize_path(pathname)
        exe = _executable
        if pathname.startswith(exe):
            rel = pathname[len(exe):].lstrip("\\/")
            rel = rel.replace("\\", "/")
        else:
            rel = pathname.replace("\\", "/")

        data_pos = _c._find_entry_in_resource(rel)
        if data_pos is not None:
            (offset, size) = data_pos
            return _c._get_data(offset, size, use_resource=True)
        data_pos = _c._find_entry(rel)
        if data_pos is not None:
            (offset, size) = data_pos
            return _c._get_data(offset, size, use_resource=False)

        raise OSError(0, "", rel)

    def get_data(self, pathname: str):
        return self.get_data_static(pathname)
