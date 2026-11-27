# Demo 参数与循环音频配套 / Demo support

参数面板面向浏览器数值调节；音频脚本只处理调用者已有且有权使用的音频。项目自己拥有设置、预设、场景状态、素材选择和实际效果。本包不包含任何私人游戏配置、研究收据、音频或模型。

## 数值面板

固定lil-gui 0.21.0 MIT原件与原许可在 parameter-lab/vendor；适配和通用样例在 parameter-lab。把 parameter-lab.mjs、lil-gui.esm.js及LICENSE复制到项目开发工具目录并记录源哈希，按 sample.mjs 调用：

~~~text
createParameterLab({GUI,id,revision,target,fields,render,container})
~~~

`target` 是项目实际读取的可写纯数值，`fields` 定义范围/步长/单位，`render` 是可恢复的同步更新。人用控件和Agent的snapshot/apply走同一校验；导入检查项目ID与revision，输入框聚焦时拒绝外部修改。dispose恢复初始化基线并释放面板/监听。需要重开或不可逆副作用的设置由项目显式适配，不能当作即时可回退参数。

`parameter-lab/standalone.html` 可离线打开，`node parameter-lab/build.cjs` 只重建该样例；它不是所有项目的最终HTML构建器。正式项目需验证调整、保存/导入、恢复、非法值、焦点冲突、场景重开与资源释放。

## 已有音频加工

Python3.11+及自行配置的NumPy、SoundFile（含可用libsndfile）可直接运行固定脚本：

~~~text
python <tools-home>/integrations/demo-support/audio-loop/prepare.py --input <owned.wav> --output-dir <new-output-directory> --start 0 --duration 2
~~~

不调用音频生成服务。原文件不改，输出direct.ogg、crossfade候选、analysis.json和离线player.html。片段1..90秒、参数及有限值按代码校验；程序读取完整输入，调用者先按投入边界准备合适音频。已有输出拒绝覆盖，失败保留现场，重试用新版本目录。

沿player-template.html的frames/sampleRate设置有效loopEnd；试听至少三轮接缝、直接版与交叠版，再与实际游戏音效混合决定采用。首次用户操作解锁、静音、暂停、切场景与释放由宿主处理。文件解码与数值检查通过不等于听感通过。

## Health and recovery

~~~text
python <tools-home>/toolbox.py run --workflow demo-support --tool demo-support --action health
~~~

health只核十份固定源码，不导入音频依赖、不播放或生成音频，不启动模型。撤回时恢复原工具版本与对应项目预设/音频元数据，不自动迁移项目副本。

The parameter adapter and audio processor work without AWS, meta, Research or a
private Studio. lil-gui retains its MIT license; project settings, audio rights and
acceptance remain with the recipient. The sample is generic. Optional audio runtime
is explicitly configured outside the managed package. No accounts or model calls.
