import os

# Qt должен работать без реального дисплея в CI
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
