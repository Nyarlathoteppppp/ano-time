on run
    set projectPath to "/Users/ywbw/realtime-ton"
    set logPath to "/tmp/realtime-ton.log"
    set pidPath to "/tmp/realtime-ton.pid"
    set launchCommand to "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin; " & ¬
        "if [ -f " & quoted form of pidPath & " ] && kill -0 $(cat " & quoted form of pidPath & ") 2>/dev/null; then exit 0; fi; " & ¬
        "cd " & quoted form of projectPath & "; " & ¬
        "nohup ./start_mac.sh > " & quoted form of logPath & " 2>&1 < /dev/null & echo $! > " & quoted form of pidPath
    do shell script launchCommand
    display notification "Translator dashboard is starting" with title "Realtime Translator"
end run
