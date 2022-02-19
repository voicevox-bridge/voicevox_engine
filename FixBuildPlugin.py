from textwrap import dedent

from nuitka.plugins.PluginBase import NuitkaPluginBase


class NuitkaPluginFixBuild(NuitkaPluginBase):
    plugin_name = "fix-build"

    @staticmethod
    def onModuleSourceCode(module_name, source_code):
        if module_name == "torch.utils.data._typing":
            source_code = source_code.replace(
                "'__init_subclass__': _dp_init_subclass",
                "'__init_subclass__': classmethod(_dp_init_subclass)",
            )
        elif module_name == "numba.core.decorators":
            source_code = dedent(
                """\
                from numba.stencils.stencil import stencil

                def jit(func, *args, **kwargs):
                    return func

                def generated_jit(func, *args, **kwargs):
                    return func

                def njit(func, *args, **kwargs):
                    return func

                def cfunc(func, *args, **kwargs):
                    return func

                def jit_module(*args, **kwargs):
                    pass
                """
            )
        return source_code
