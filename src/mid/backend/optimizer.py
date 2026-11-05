import llvmlite.binding as llvm

def optimizer(module: llvm.ModuleRef) -> llvm.ModuleRef:
    """Run LLVM's standard optimization pipeline on a verified IR module."""
    target_machine = llvm.Target.from_default_triple().create_target_machine()
    tuning_options = llvm.create_pipeline_tuning_options(speed_level=2)
    pass_builder = llvm.create_pass_builder(target_machine, tuning_options)
    module_passes = pass_builder.getModulePassManager()
    module_passes.run(module, pass_builder)
    module.verify()
    return module
