import os
import subprocess
import sys


def run_step(script: str) -> None:
    result = subprocess.run([sys.executable, script], check=False)
    if result.returncode != 0:
        print(f"❌ {script} failed with exit code {result.returncode}")
        sys.exit(1)


if __name__ == '__main__':
    files = os.listdir('./data')
    for file in files:
        f_name, ext = file.split('.')
        if ext == 'hwp':
            if os.path.exists(f'output/temp_pdf/{f_name}.pdf'):
                continue
            os.system(f"python hwp_converter.py data/{file} -o output/temp_pdf")
        else:
            os.system(f"cp data/{file} output/temp_pdf/{file}")

    run_step('parser_step1.py')
    run_step('auditor_step2.py')
    run_step('chunker_step4.py')
    run_step('storage_step5.py')
