if __name__ == "__main__":
    import runpy

    runpy.run_module("src.evaluation.build_eval_gold_rich", run_name="__main__")
else:
    from .evaluation.build_eval_gold_rich import *  # noqa: F401,F403
