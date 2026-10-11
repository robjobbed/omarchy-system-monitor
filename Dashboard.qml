import QtQuick
import QtQuick.Controls as Controls
import qs.Commons
import qs.Ui

Item {
    id: dash
    required property var monitor
    property string page: "processes"
    readonly property bool temperatures: page === "temperatures"
    property bool allApps: false
    readonly property bool advanced: page === "details"
    property var networkHistory: ({})
    readonly property var latest: monitor.data
    readonly property var detail: monitor.details
    readonly property color ink: "#e2e5f0"
    readonly property color muted: "#a1a7bb"
    readonly property string face: "sans-serif"
    readonly property real cpuTemp: {
        var list = (detail.sensors || []).filter(function(s){return /Package|Core/.test(s.name)})
        return list.length ? Math.max.apply(null,list.map(function(s){return s.temperature})) : -1
    }
    readonly property var gpu: latest.gpu || ({})
    readonly property bool sharedGpu: gpu.memory_kind === "shared"
    function gpuName(n) { return (n || "").replace("NVIDIA GeForce ","").replace(/^Intel Corporation /,"") }
    function gpuExtra() {
        if (!gpu.available) return ""
        var temp = monitor.val(gpu.temperature,"°C")
        if (gpu.power !== null && gpu.power !== undefined) return temp+" · "+monitor.val(gpu.power,"W")
        if (gpu.frequency !== null && gpu.frequency !== undefined) return temp+" · "+Math.round(gpu.frequency)+" MHz"
        return temp
    }
    function fanText() {
        if (gpu.fan !== null && gpu.fan !== undefined) return "GPU fan "+monitor.val(gpu.fan,"%")
        var list = latest.fans || []
        if (!list.length) return "Fan Unavailable"
        var f = list[0]
        return f.name+" "+f.rpm+" RPM"+(f.percent !== null && f.percent !== undefined ? " · "+f.percent+"%" : "")
    }
    function engineText() {
        var e = gpu.engines || {}
        var keys = Object.keys(e)
        if (!keys.length) return ""
        var names = {render:"Render", copy:"Copy", video:"Video", "video-enhance":"Enhance", compute:"Compute"}
        var parts = keys.map(function(k){ return (names[k] || k)+" "+Math.round(e[k])+"%" })
        if (gpu.awake !== null && gpu.awake !== undefined) parts.push("Awake "+Math.round(gpu.awake)+"%")
        if (gpu.frequency !== null && gpu.frequency !== undefined) parts.push(Math.round(gpu.frequency)+" / "+Math.round(gpu.max_frequency || 0)+" MHz")
        parts.push(gpu.clients+" DRM clients")
        return "GPU engines · "+parts.join(" · ")
    }
    implicitHeight: body.implicitHeight
    onLatestChanged: {
        if (!monitor.opened) return
        var next = Object.assign({}, networkHistory)
        ;(latest.network || []).forEach(function(n){next[n.name]=((next[n.name] || []).concat([n.read])).slice(-60)})
        networkHistory = next
    }
    function appIcon(name) {
        if (name === "Vivaldi") return "/usr/share/icons/hicolor/48x48/apps/vivaldi.png"
        if (name === "Steam") return "/usr/share/icons/hicolor/48x48/apps/steam.png"
        return ""
    }
    function glyph(name) {
        if (/python/i.test(name)) return "\ue73c"
        if (/node/i.test(name)) return "\ue718"
        if (/qemu/i.test(name)) return "\uf1b2"
        return "\uf0ad"
    }
    component Label: Text {
        color: dash.ink; font.family: dash.face; font.pixelSize: Style.space(13)
        textFormat: Text.PlainText
    }
    component Glyph: Item {
        id: glyphRoot
        property string text: ""
        property color color: dash.muted
        property int size: Style.space(19)
        width: Style.space(22); height: width
        readonly property real paintedCenterX: glyphText.x + bounds.tightBoundingRect.x + bounds.tightBoundingRect.width/2
        readonly property real paintedCenterY: glyphText.y + glyphText.baselineOffset + bounds.tightBoundingRect.y + bounds.tightBoundingRect.height/2
        TextMetrics { id: bounds; text: glyphRoot.text; font.family: monitor.family; font.pixelSize: glyphRoot.size }
        Text {
            id: glyphText
            text: glyphRoot.text; color: glyphRoot.color
            font.family: monitor.family; font.pixelSize: glyphRoot.size
            x: (glyphRoot.width-bounds.tightBoundingRect.width)/2-bounds.tightBoundingRect.x
            y: (glyphRoot.height-bounds.tightBoundingRect.height)/2-glyphText.baselineOffset-bounds.tightBoundingRect.y
            renderType: Text.NativeRendering
        }
    }
    component Rule: Rectangle { width: body.width; height: 1; color: "#303443" }
    component Action: Controls.Button {
        id: actionButton
        property bool selected: false
        implicitWidth: contentItem.implicitWidth + Style.space(16)
        implicitHeight: Style.space(25)
        contentItem: Label { text: actionButton.text; color: actionButton.selected ? dash.ink : dash.muted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle {
            radius: 0
            color: actionButton.selected ? "#262e3c" : actionButton.hovered ? "#252936" : "#1e212b"
            border.width: actionButton.selected ? 1 : 0
            border.color: "#39475c"
            Behavior on color { ColorAnimation { duration:140 } }
        }
    }
    component Spark: Canvas {
        id: spark
        property var samples: []
        property color accent: monitor.cpuColor
        property real maximum: 100
        onSamplesChanged: if (monitor.opened) requestPaint()
        onVisibleChanged: if (visible) requestPaint()
        onWidthChanged: if (visible) requestPaint()
        onPaint: {
            var c=getContext("2d"); c.reset(); c.strokeStyle=accent; c.lineWidth=1.8; c.lineJoin="round"; c.lineCap="round"; c.beginPath()
            var active=false
            for(var i=0;i<samples.length;i++) {
                var v=samples[i]
                if(v === null || v === undefined) {active=false;continue}
                var x=width*(60-samples.length+i)/59
                var y=height-3-Math.max(0,Math.min(maximum,v))/Math.max(1,maximum)*(height-6)
                if(!active) {c.moveTo(x,y);active=true} else c.lineTo(x,y)
            }
            c.stroke()
        }
    }
    component Metric: Rectangle {
        id: metric
        property string title
        property string subtitle
        property string symbol
        property string series
        property var value
        property string extra: ""
        property color accent
        width: body.width; height: Style.space(48); radius: 0
        color: "#1e212b"; border.width:1; border.color: "#303443"
        Rectangle {
            id: iconTile
            x:Style.space(9); anchors.verticalCenter:parent.verticalCenter
            width:Style.space(28); height:width; radius: 0
            color:monitor.tint(metric.accent,0.09)
            Glyph { anchors.fill:parent; text:metric.symbol; color:metric.accent }
        }
        Column {
            x:Style.space(47); anchors.verticalCenter:parent.verticalCenter; spacing:Style.space(3)
            width:Style.space(135)
            Label { text:metric.title; font.pixelSize:Style.space(14); font.weight:Font.DemiBold }
            Label { text:metric.subtitle; color:dash.muted; width:parent.width; elide:Text.ElideRight; font.pixelSize:Style.space(12) }
        }
        Spark {
            x:Style.space(190); anchors.verticalCenter:parent.verticalCenter
            width:Math.max(Style.space(50),parent.width-x-Style.space(102)); height:Style.space(25)
            accent:metric.accent
            samples:(latest.history || []).map(function(h){return h[metric.series]})
        }
        Column {
            anchors.right:parent.right; anchors.rightMargin:Style.space(14); anchors.verticalCenter:parent.verticalCenter
            width:Style.space(91); spacing:Style.space(6)
            Label { width:parent.width; horizontalAlignment:Text.AlignRight; text:monitor.pct(metric.value); color:metric.accent; font.pixelSize:Style.space(19); font.weight:Font.DemiBold }
            Label { visible:text !== ""; width:parent.width; horizontalAlignment:Text.AlignRight; text:metric.extra; color:dash.muted; font.pixelSize:Style.space(12) }
        }
    }
    Column {
        id:body
        width:dash.width
        spacing:Style.space(6)
        Item {
            width:parent.width; height:Style.space(26)
            Rectangle { width:Style.space(24); height:width; radius: 0; color:monitor.tint(monitor.cpuColor,0.09); anchors.verticalCenter:parent.verticalCenter
                Glyph { anchors.fill:parent; text:"\uf21e"; color:monitor.cpuColor }
            }
            Label { x:Style.space(34); anchors.verticalCenter:parent.verticalCenter; text:"System"; font.pixelSize:Style.space(17); font.weight:Font.DemiBold }
            Label { x:Style.space(106); anchors.verticalCenter:parent.verticalCenter; text:monitor.stale ? "● Offline" : "● Live · 2s"; color:monitor.stale ? monitor.warmColor : dash.muted }
            Action { anchors.right:parent.right; anchors.verticalCenter:parent.verticalCenter; text:"Details"; selected:dash.advanced; onClicked:dash.page=dash.advanced ? "processes" : "details" }
        }
        Metric { title:"CPU"; subtitle:(latest.cores || []).length+" logical cores"; symbol:"\uf4bc"; series:"cpu"; value:latest.cpu; accent:monitor.cpuColor; extra:dash.cpuTemp >= 0 ? Math.round(dash.cpuTemp)+"°C" : "Temp unavailable" }
        Metric { title:"RAM"; subtitle:monitor.bytes((latest.memory || {}).used)+" / "+monitor.bytes((latest.memory || {}).total); symbol:"\uefc5"; series:"ram"; value:(latest.memory || {}).percent; accent:monitor.ramColor }
        Metric { title:"GPU"; subtitle:dash.gpu.available ? dash.gpuName(dash.gpu.name)+" · "+(dash.sharedGpu ? "shared memory" : monitor.bytes(dash.gpu.total)) : "Telemetry unavailable"; symbol:"\uf108"; series:"gpu"; value:dash.gpu.percent; accent:monitor.gpuColor; extra:dash.gpuExtra() }
        Label { width:parent.width; elide:Text.ElideRight; text:(dash.sharedGpu ? "GPU memory (shared)  " : "VRAM  ")+monitor.bytes(dash.gpu.used)+" / "+monitor.bytes(dash.gpu.total)+"    |    "+dash.fanText(); color:dash.muted; font.pixelSize:Style.space(12) }
        Row {
            spacing:Style.space(4)
            Action { text:"Processes"; selected:dash.page==="processes"; onClicked:dash.page="processes" }
            Action { text:"Temps"; selected:dash.temperatures; onClicked:dash.page="temperatures" }
            Action { text:"Storage"; selected:dash.page==="storage"; onClicked:dash.page="storage" }
            Action { text:"Network"; selected:dash.page==="network"; onClicked:dash.page="network" }
            Action { text:monitor.sortBy === "memory" ? "RAM ↓" : "CPU ↓"; visible:dash.page==="processes"; onClicked:monitor.sortBy=monitor.sortBy === "memory" ? "cpu" : "memory" }
            Action { text:monitor.memoryMode.toUpperCase(); visible:dash.page==="processes"; onClicked:monitor.memoryMode = monitor.memoryMode === "rss" ? "pss" : "rss" }
        }
        Column {
            visible:dash.page==="processes"
            width:parent.width; spacing:Style.space(4)
            Label { visible:!detail.apps || detail.processes_warming; text:"Sampling process details…"; color:dash.muted; font.pixelSize:Style.space(11) }
            Repeater {
                model:dash.allApps ? monitor.apps : monitor.apps.slice(0,5)
                delegate: Item {
                    required property var modelData
                    width:body.width; height:Style.space(24)
                    Image { x:Style.space(5); anchors.verticalCenter:parent.verticalCenter; width:Style.space(18); height:width; source:dash.appIcon(modelData.name); visible:source.toString() !== ""; fillMode:Image.PreserveAspectFit }
                    Glyph { x:Style.space(5); anchors.verticalCenter:parent.verticalCenter; width:Style.space(18); height:width; visible:dash.appIcon(modelData.name)===""; text:dash.glyph(modelData.name); color:/node/i.test(modelData.name) ? monitor.gpuColor : /python/i.test(modelData.name) ? monitor.cpuColor : dash.muted }
                    Label { x:Style.space(32); anchors.verticalCenter:parent.verticalCenter; width:parent.width-Style.space(178); elide:Text.ElideRight; text:modelData.name }
                    Label { anchors.right:usage.left; anchors.rightMargin:Style.space(12); anchors.verticalCenter:parent.verticalCenter; text:modelData.count+"×"; color:dash.muted; opacity:0.6; font.pixelSize:Style.space(10) }
                    Label { id:usage; anchors.right:parent.right; anchors.rightMargin:Style.space(7); anchors.verticalCenter:parent.verticalCenter; width:Style.space(98); horizontalAlignment:Text.AlignRight; text:monitor.sortBy==="memory" ? monitor.bytes(modelData.displayMemory) : detail.processes_warming ? "…" : modelData.cpu.toFixed(1)+"%"; color:monitor.sortBy==="memory" ? monitor.ramColor : monitor.cpuColor; font.pixelSize:Style.space(14) }
                }
            }
            Item {
                width:parent.width; height:Style.space(24)
                Label { text:"Grouped apps · "+(monitor.sortBy==="memory" ? monitor.memoryMode.toUpperCase()+" memory" : "whole-machine CPU"); color:dash.muted; font.pixelSize:Style.space(10); anchors.verticalCenter:parent.verticalCenter }
                Action { anchors.right:parent.right; text:dash.allApps ? "Show less ‹" : "See all ›"; onClicked:dash.allApps=!dash.allApps }
            }
        }
        Flow {
            visible:dash.temperatures
            width:parent.width; spacing:Style.space(7)
            Repeater {
                model:detail.sensors || []
                delegate:Rectangle {
                    required property var modelData
                    width:(body.width-Style.space(7))/2; height:Style.space(28); radius: 0; color:"#202430"
                    Label { x:Style.space(10); anchors.verticalCenter:parent.verticalCenter; text:modelData.name; color:dash.muted; width:parent.width-Style.space(72); elide:Text.ElideRight }
                    Label { anchors.right:parent.right; anchors.rightMargin:Style.space(10); anchors.verticalCenter:parent.verticalCenter; text:Math.round(modelData.temperature)+"°C"; color:modelData.temperature>=80 ? monitor.warmColor : monitor.cpuColor }
                }
            }
            Repeater {
                model:latest.fans || []
                delegate:Rectangle {
                    required property var modelData
                    width:(body.width-Style.space(7))/2; height:Style.space(28); radius: 0; color:"#202430"
                    Label { x:Style.space(10); anchors.verticalCenter:parent.verticalCenter; text:modelData.name; color:dash.muted; width:parent.width-Style.space(120); elide:Text.ElideRight }
                    Label { anchors.right:parent.right; anchors.rightMargin:Style.space(10); anchors.verticalCenter:parent.verticalCenter; text:modelData.rpm+" RPM"+(modelData.percent !== null && modelData.percent !== undefined ? " · "+modelData.percent+"%" : ""); color:monitor.gpuColor }
                }
            }
            Label { visible:!(detail.sensors || []).length && !(latest.fans || []).length; text:"Sensors unavailable"; color:dash.muted }
        }
        Column { width:parent.width; spacing:Style.space(8); visible:dash.page === "storage"
        Rule {}
        Row { spacing:Style.space(10); Glyph { text:"\uf0a0"; size:Style.space(17) } Label { text:"Storage"; font.pixelSize:Style.space(14); font.weight:Font.DemiBold } }
        Repeater {
            model:detail.mounts || []
            delegate:Column {
                id:mountRow
                required property var modelData
                readonly property real fraction:modelData.total>0 ? modelData.used/modelData.total : 0
                width:body.width; spacing:Style.space(7)
                Item {
                    width:parent.width; height:Style.space(17)
                    Label { text:mountRow.modelData.name==="/" ? "System" : mountRow.modelData.name.split("/").pop(); width:parent.width*0.40; elide:Text.ElideMiddle; color:dash.muted }
                    Label { anchors.right:parent.right; text:monitor.bytes(mountRow.modelData.used)+" / "+monitor.bytes(mountRow.modelData.total); color:dash.muted; font.pixelSize:Style.space(12) }
                }
                Item {
                    width:parent.width; height:Style.space(12)
                    Rectangle { anchors.verticalCenter:parent.verticalCenter; width:parent.width-Style.space(49); height:Style.space(6); radius: 0; color:"#292d39"
                        Rectangle { height:parent.height; width:parent.width*mountRow.fraction; radius: 0; color:mountRow.fraction>=0.9 ? monitor.warmColor : monitor.cpuColor; Behavior on width { NumberAnimation { duration:300 } } }
                    }
                    Label { anchors.right:parent.right; anchors.verticalCenter:parent.verticalCenter; text:Math.round(mountRow.fraction*100)+"%"; color:dash.muted; font.pixelSize:Style.space(12) }
                }
            }
        }
        }
        Column { width:parent.width; spacing:Style.space(8); visible:dash.page === "network"
        Rule {}
        Row { spacing:Style.space(10); Glyph { text:"\uf1eb"; size:Style.space(17) } Label { text:"Network"; font.pixelSize:Style.space(14); font.weight:Font.DemiBold } }
        Repeater {
            model:latest.network || []
            delegate:Item {
                id:netRow
                required property var modelData
                required property int index
                readonly property color accent:index%3===0 ? monitor.cpuColor : index%3===1 ? monitor.ramColor : monitor.gpuColor
                width:body.width; height:Style.space(27)
                Label { width:Style.space(83); anchors.verticalCenter:parent.verticalCenter; text:netRow.modelData.name; elide:Text.ElideRight }
                Spark { x:Style.space(88); anchors.verticalCenter:parent.verticalCenter; width:Style.space(90); height:Style.space(22); samples:dash.networkHistory[netRow.modelData.name] || []; maximum:Math.max.apply(null,[1].concat(samples)); accent:netRow.accent }
                Label { anchors.right:parent.right; anchors.verticalCenter:parent.verticalCenter; text:"↓ "+monitor.bytes(netRow.modelData.read)+"/s    ↑ "+monitor.bytes(netRow.modelData.write)+"/s"; color:dash.muted; font.pixelSize:Style.space(12) }
            }
        }
        }
        Column {
            width:parent.width; visible:dash.advanced; spacing:Style.space(10)
            Rule {}
            Label { text:"Details"; font.pixelSize:Style.space(16); font.weight:Font.DemiBold }
            Label { width:parent.width; wrapMode:Text.Wrap; color:dash.muted; font.pixelSize:Style.space(11); text:"Available RAM "+monitor.bytes((latest.memory || {}).available)+" · Swap "+monitor.bytes((latest.memory || {}).swap_used)+" / "+monitor.bytes((latest.memory || {}).swap_total) }
            Flow { width:parent.width; spacing:Style.space(6)
                Repeater { model:latest.cores || []; delegate:Rectangle { required property var modelData; required property int index; width:Style.space(67); height:Style.space(24); radius: 0; color:"#252a37"; Label { anchors.centerIn:parent; text:index+" · "+monitor.pct(modelData); color:monitor.cpuColor; font.pixelSize:Style.space(11) } } }
            }
            Label { visible:text !== ""; width:parent.width; wrapMode:Text.Wrap; color:dash.muted; font.pixelSize:Style.space(11); text:dash.engineText() }
            Repeater { model:latest.disks || []; delegate:Label { required property var modelData; text:modelData.name+" · Read "+monitor.bytes(modelData.read)+"/s · Write "+monitor.bytes(modelData.write)+"/s"; color:dash.muted; font.pixelSize:Style.space(11) } }
            Repeater { model:detail.mounts || []; delegate:Label { required property var modelData; width:parent.width; elide:Text.ElideMiddle; text:modelData.name+" · Available "+monitor.bytes(modelData.available); color:dash.muted; font.pixelSize:Style.space(11) } }
            Label { width:parent.width; wrapMode:Text.Wrap; text:"Load "+(detail.load || []).map(function(n){return n.toFixed(2)}).join(" / ")+" · Uptime "+Math.floor((detail.uptime || 0)/3600)+"h\nRSS matches btop process accounting; shared pages count in each process. PSS apportions shared pages and is Unavailable if any nonzero-RSS process denies access. Network interfaces may overlap tunnel traffic. Sparklines: ≈2 minutes; resource scale 0–100%, network scale per-interface peak."+(dash.sharedGpu ? "\nIntegrated GPU: busy % is the busiest engine across DRM clients this user can read; memory is shared system RAM resident to GPU clients; temperature is the CPU package sensor." : ""); color:dash.muted; opacity:0.65; font.pixelSize:Style.space(10) }
        }
    }
}
