on run
	set projectPath to "/Users/ywbw/realtime-ton"
	display notification "Translator dashboard is starting" with title "Ano Time"
	set launchCommand to "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin; " & ¬
		"cd " & quoted form of projectPath & "; ./launch_desktop.sh"
	do shell script launchCommand
end run
