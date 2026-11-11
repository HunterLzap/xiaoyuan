@echo off
set IDF_TOOLS_PATH=E:\xiaodan\firmware\.espressif
set IDF_PATH=E:\xiaodan\firmware\esp-idf-v5.5.2
set TEMP=E:\xiaodan\firmware\.tmp
set TMP=E:\xiaodan\firmware\.tmp
cd /d E:\xiaodan\firmware\xiaozhi-esp32
"E:\xiaodan\firmware\.espressif\python_env\idf5.5_py3.12_env\Scripts\python.exe" "E:\xiaodan\firmware\esp-idf-v5.5.2\tools\idf.py" -B build-tafei-mn5-ui-anim -DSDKCONFIG=sdkconfig.tafei-mn5 -DSDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.defaults.atoms3r-tafei-mn5" -DTAFEI_MN5_SMALL_FONT=ON build
