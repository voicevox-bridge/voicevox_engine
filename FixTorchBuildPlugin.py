from nuitka.plugins.PluginBase import NuitkaPluginBase


class NuitkaPluginFixTorchBuild(NuitkaPluginBase):
    plugin_name = "fix-torch-build"

    @staticmethod
    def onModuleSourceCode(module_name, source_code):
        if module_name == "torch.utils.data._typing":
            source_code = source_code.replace(
                "'__init_subclass__': _dp_init_subclass",
                "'__init_subclass__': classmethod(_dp_init_subclass)",
            )
        return source_code
