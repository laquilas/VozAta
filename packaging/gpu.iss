; GPU support for both installers (phase 58): the NVIDIA CUDA libraries are not in the installer.
; On a PC with an NVIDIA driver (nvidia-smi.exe in System32) an option, ticked, downloads them into
; %LOCALAPPDATA%\VozAta\cuda (`vozata-engine cuda install`); untick it to stay on the CPU. The
; uninstaller removes them unless the other installer (VozAta / VozAta Worker) still uses them.
; The including script defines SpeakersWorkDir (where the engine reads its .env) and OtherAppId;
; HasNvidiaDriver is in speakers.iss, which holds the [Code] of both and is included after this.

[CustomMessages]
en.GpuTask=Download GPU support for speech recognition (NVIDIA CUDA, about 1.2 GB; without it the CPU is used)
ptbr.GpuTask=Baixar o suporte a GPU para o reconhecimento de fala (NVIDIA CUDA, cerca de 1,2 GB; sem ele a CPU é usada)
es.GpuTask=Descargar el soporte de GPU para el reconocimiento de voz (NVIDIA CUDA, unos 1,2 GB; sin él se usa la CPU)
en.GpuStatus=Downloading GPU support (see the console window)...
ptbr.GpuStatus=Baixando o suporte a GPU (veja a janela do console)...
es.GpuStatus=Descargando el soporte de GPU (mira la ventana de la consola)...

[Tasks]
Name: "gpu"; Description: "{cm:GpuTask}"; Check: HasNvidiaDriver

[Run]
Filename: "{cmd}"; Parameters: "/c """"{app}\engine\vozata-engine.exe"" cuda install || pause"""; WorkingDir: "{#SpeakersWorkDir}"; StatusMsg: "{cm:GpuStatus}"; Tasks: gpu; Flags: waituntilterminated
