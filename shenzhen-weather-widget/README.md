# 深圳天气预报 Windows 桌面小组件

一个轻量、零第三方依赖的 Windows 桌面天气小组件，默认显示深圳当前天气和未来 5 天预报。

## 适用场景

- 个人桌面常驻天气小窗
- 公司内部分发的小工具
- 可二次开发、可免费商用的桌面组件模板（需保留天气数据归属并使用合规 User-Agent）

## 功能

- 固定显示深圳天气
- 当前温度、天气状况、体感温度、湿度、风速
- 未来 5 天最高/最低温和降水量预报
- 无边框悬浮窗口、可拖动、可置顶
- 现代深色卡片式 UI
- 右键菜单：立即刷新、切换置顶、切换紧凑模式、退出
- 双击切换紧凑模式，`Esc` 快速退出
- 自动每 15 分钟刷新
- 断网时显示最近一次成功获取的缓存数据
- 自动把窗口位置限制在屏幕内，避免拖出屏幕后找不到

## 运行

需要 Windows 上安装 Python 3.10+。

双击：

```bat
run.bat
```

或者在当前目录运行：

```bat
python weather_widget.py
```

如果想启动时不显示控制台窗口，可以运行：

```bat
pythonw weather_widget.py
```

## 使用

- 拖动窗口：按住窗口任意空白区域拖动
- 刷新：点击右上角 `↻` 或右键选择“立即刷新”
- 置顶：点击右上角 `●` 或右键选择“取消置顶 / 保持置顶”
- 退出：点击右上角 `×`、按 `Esc` 或右键选择“退出”
- 紧凑模式：双击窗口或右键选择“紧凑模式”

## 开机启动

1. 按 `Win + R`
2. 输入 `shell:startup`
3. 给 `run.bat` 创建一个快捷方式，放到打开的启动文件夹里

## 数据来源与商用说明

天气数据来自 [MET Norway Locationforecast API](https://api.met.no/weatherapi/locationforecast/2.0/)，数据按 **CC BY 4.0** 开放许可提供。小组件界面底部保留了 `MET Norway · CC BY 4.0` 归属标识。

如需商用或公开分发：

- 保留界面中的数据归属，或在产品文档中提供等效归属。
- 不要暗示 MET Norway、Yr 或 NRK 认可/赞助你的产品。
- 必须使用可识别的 User-Agent，方便符合 api.met.no 的服务条款。程序首次运行会提示你填写，也可以通过环境变量提前设置：

```bat
set WEATHER_WIDGET_USER_AGENT=YourProductName/1.0 github.com/yourcompany/weather
pythonw weather_widget.py
```

更多第三方说明见 `THIRD_PARTY_NOTICES.md`。

## 软件许可

本项目代码使用 MIT License，详见 `LICENSE`。你可以免费用于个人、内部、商业项目，也可以修改、复制、分发或打包。

## 缓存位置

程序会在这里保存窗口位置和最近一次成功天气数据：

```text
%LOCALAPPDATA%\SzWeatherWidget
```

如窗口位置异常，可关闭程序后删除或修改：

```text
%LOCALAPPDATA%\SzWeatherWidget\geometry.txt
```

## 打包为 exe（可选）

默认无需打包。如果要给没有 Python 的用户使用，可以自行用 PyInstaller 打包：

```bat
build_exe.bat
```

或手动执行：

```bat
pip install pyinstaller
pyinstaller --noconsole --onefile --name ShenzhenWeatherWidget --icon weather_widget.ico weather_widget.py
```

生成文件通常在：

```text
dist\ShenzhenWeatherWidget.exe
```

## 交付前验证

运行：

```bat
python verify_widget.py
```

它会检查天气数据源、归一化预报结构、启动脚本、README、MIT License 和第三方归属说明。

## 常见问题

- 如果显示离线，请检查网络、防火墙或代理。
- 如果遇到证书问题，程序会自动尝试使用 Windows PowerShell 网络栈回退请求。
- 如果 emoji 天气图标显示异常，仍可根据旁边的中文天气文字判断天气。
- 如果双击 `run.bat` 没反应，请先在命令行运行 `python weather_widget.py` 查看错误信息。
