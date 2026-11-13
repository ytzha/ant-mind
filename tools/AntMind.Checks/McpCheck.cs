using System.Diagnostics;
using System.Text;
using System.Text.Json;
using AntMind.Contracts;
using AntMind.Transport;
internal static class McpCheck {
    public static async Task RunAsync() {
        var pipeName = "antmind-mcp-" + Guid.NewGuid().ToString("N");
        Process Start(string dll, params string[] arguments) {
            var info = new ProcessStartInfo("dotnet") { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true, StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = new UTF8Encoding(false), StandardErrorEncoding = new UTF8Encoding(false) };
            info.ArgumentList.Add(Path.GetFullPath(dll));
            foreach (var argument in arguments) info.ArgumentList.Add(argument);
            info.Environment["ANTMIND_PIPE"] = pipeName;
            return Process.Start(info) ?? throw new Exception("Cannot start child process.");
        }
        using var host = Start("tools/AntMind.Evaluator/bin/Debug/net10.0/AntMind.Evaluator.dll", "--serve");
        using var mcp = Start("src/AntMind.Mcp/bin/Debug/net10.0/AntMind.Mcp.dll");
        _ = host.StandardError.ReadToEndAsync(); _ = mcp.StandardError.ReadToEndAsync();
        async Task<JsonElement> Rpc(int id, string method, object parameters) {
            await mcp.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { jsonrpc = "2.0", id, method, @params = parameters }));
            while (true) {
                var line = await mcp.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(15)) ?? throw new Exception("MCP exited.");
                var message = JsonDocument.Parse(line).RootElement.Clone();
                if (!message.TryGetProperty("id", out var responseId) || responseId.GetInt32() != id) continue;
                if (message.TryGetProperty("error", out _)) throw new Exception(message.ToString());
                return message.GetProperty("result");
            }
        }
        try {
            var beforeHandshake = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (beforeHandshake.Snapshot?.AgentConnected != false) throw new Exception("A process without an MCP handshake must not light the indicator.");
            await Rpc(1, "initialize", new { protocolVersion = "2025-06-18", capabilities = new { }, clientInfo = new { name = "antmind-checks", version = "1" } });
            await mcp.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { jsonrpc = "2.0", method = "notifications/initialized" }));
            var tools = await Rpc(2, "tools/list", new { });
            if (tools.GetProperty("tools").GetArrayLength() != 15) throw new Exception("Unexpected tool schema.");
            var handshakeView = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (handshakeView.Snapshot?.AgentConnected != true) throw new Exception("Completed MCP initialize handshake did not light the indicator.");
            var catalog=await Rpc(98,"tools/call",new {name="get_catalog",arguments=new {}});
            var catalogJson=JsonDocument.Parse(catalog.GetProperty("content")[0].GetProperty("text").GetString()!).RootElement;
            if(catalogJson.GetProperty("TechnologyLevel").GetInt32()!=1 || !catalogJson.GetProperty("Unlocks").EnumerateArray().Any(x=>x.GetProperty("Id").GetString()=="building.workshop" && x.GetProperty("RequiredNetworkLevel").GetInt32()==2 && !x.GetProperty("Unlocked").GetBoolean()))throw new Exception("MCP technology catalog missing kitchen gate.");
            var lockedKitchen=await Rpc(99,"tools/call",new {name="command",arguments=new {requestId=Guid.NewGuid().ToString(),expectedRevision=handshakeView.Snapshot!.Revision,kind="PlanBuild",value=0,reason="verify kitchen gate",key="workshop",pointX=64000,pointY=64000}});
            if(!lockedKitchen.ToString().Contains("technology_locked"))throw new Exception("MCP bypassed kitchen technology gate.");
            Console.WriteLine("PASS real MCP exposes food values and technology unlocks and rejects locked kitchen construction");
            var antRecord = await Rpc(22, "tools/call", new { name = "inspect_object", arguments = new { kind="ant", id=1 } });
            if (antRecord.ToString().Contains("object_not_found")) throw new Exception("MCP cannot inspect an independent ant record.");
            Console.WriteLine("PASS real MCP initialize handshake activates presence and independent object inspection");
            var actions = await Rpc(20, "tools/call", new { name = "get_actions", arguments = new { } });
            if (!actions.ToString().Contains("UpgradeNetwork")) throw new Exception("Button API catalog is incomplete.");
            var validation = await Rpc(21, "tools/call", new { name = "validate_program", arguments = new { source = "if (queen_connected) { wait(); }" } });
            if (!validation.ToString().Contains("true")) throw new Exception("DSL validation endpoint failed.");
            var observed = await Rpc(3, "tools/call", new { name = "observe", arguments = new { } });
            if (observed.TryGetProperty("isError", out var error) && error.GetBoolean()) throw new Exception(observed.ToString());
            var result = await Rpc(4, "tools/call", new { name = "command", arguments = new { requestId = Guid.NewGuid().ToString(), expectedRevision = 0, kind = "Step", value = 0, reason = "architecture check", species = AntSpeciesIds.Scout } });
            if (result.TryGetProperty("isError", out var failure) && failure.GetBoolean()) throw new Exception(result.ToString());
            var snapshot = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (snapshot.Snapshot?.Tick != 1) throw new Exception("MCP command did not reach the shared world.");
            var updatedProgram = await Rpc(5, "tools/call", new { name = "command", arguments = new {
                requestId = Guid.NewGuid().ToString(), expectedRevision = snapshot.Snapshot.Revision,
                kind = "ApplyProgram", value = 0, reason = "MCP program check", species = AntSpeciesIds.Scout,
                programSource = "wait();" } });
            if (updatedProgram.TryGetProperty("isError", out var programFailure) && programFailure.GetBoolean())
                throw new Exception(updatedProgram.ToString());
            var pending = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (pending.Snapshot?.Programs.Single(x => x.Species == AntSpeciesIds.Scout).PendingVersion != 1)
                throw new Exception("MCP program submission was not staged.");
            var activate = await Rpc(6, "tools/call", new { name = "command", arguments = new {
                requestId = Guid.NewGuid().ToString(), expectedRevision = pending.Snapshot.Revision,
                kind = "Step", value = 0, reason = "activate program", species = AntSpeciesIds.Scout } });
            if (activate.TryGetProperty("isError", out var activationFailure) && activationFailure.GetBoolean())
                throw new Exception(activate.ToString());
            var activated = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (activated.Snapshot?.Tick != 2 ||
                activated.Snapshot.Programs.Single(x => x.Species == AntSpeciesIds.Scout).ActiveVersion != 1)
                throw new Exception("MCP-submitted program did not activate at the Tick boundary.");
            var producedEgg = await Rpc(30, "tools/call", new { name = "command", arguments = new {
                requestId = Guid.NewGuid().ToString(), expectedRevision = activated.Snapshot.Revision,
                kind = "ProduceEgg", value = 0, reason = "MCP egg check" } });
            if (producedEgg.TryGetProperty("isError", out var eggError) && eggError.GetBoolean()) throw new Exception(producedEgg.ToString());
            var eggSnapshot = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (eggSnapshot.Snapshot?.Eggs != 1) throw new Exception("MCP did not produce an egg.");
            await Rpc(31, "tools/call", new { name = "command", arguments = new {
                requestId = Guid.NewGuid().ToString(), expectedRevision = eggSnapshot.Snapshot.Revision,
                kind = "HatchEgg", value = 0, reason = "MCP hatch check", species = AntSpeciesIds.Soldier } });
            var hatchSnapshot = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (hatchSnapshot.Snapshot?.Eggs != 0 || hatchSnapshot.Snapshot.Ants.Length != 11 || !hatchSnapshot.Snapshot.Ants.Any(x=>x.Species==AntSpeciesIds.Soldier && x.Health==40))
                throw new Exception("MCP did not hatch the selected species.");
            await Rpc(32, "tools/call", new { name = "command", arguments = new {
                requestId = Guid.NewGuid().ToString(), expectedRevision = hatchSnapshot.Snapshot.Revision,
                kind = "SetMinimumReserve", value = 0, reason = "MCP carry check budget" } });
            var reserveSnapshot = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            await Rpc(33, "tools/call", new { name = "command", arguments = new {
                requestId = Guid.NewGuid().ToString(), expectedRevision = reserveSnapshot.Snapshot!.Revision,
                kind = "UpgradeCarry", value = 0, reason = "MCP carry check", species = AntSpeciesIds.Hauler } });
            var carrySnapshot = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (carrySnapshot.Snapshot?.Species.Single(x => x.Id == AntSpeciesIds.Hauler).CarryCapacity != 2)
                throw new Exception("MCP carry upgrade did not reach the shared simulation.");
            await Rpc(34, "tools/call", new { name = "command", arguments = new {
                requestId = Guid.NewGuid().ToString(), expectedRevision = carrySnapshot.Snapshot.Revision,
                kind = "UpgradeNetwork", value = 0, reason = "MCP network reserve check" } });
            var networkSnapshot = await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"));
            if (networkSnapshot.Snapshot?.NetworkLevel != 1 || networkSnapshot.Snapshot.Revision != carrySnapshot.Snapshot.Revision || networkSnapshot.Snapshot.Inventory != 0)
                throw new Exception("MCP network command bypassed the shared spending constraints.");
            var actionCatalog = await Rpc(35, "tools/call", new { name = "get_actions", arguments = new { } });
            var catalogText = actionCatalog.GetProperty("content")[0].GetProperty("text").GetString()!;
            var commandNames = JsonDocument.Parse(catalogText).RootElement.GetProperty("commands").EnumerateArray().Select(x => x.GetString()).ToArray();
            if (!commandNames.Contains("UpgradeNetwork") || commandNames.Contains("SetQueenRange") || commandNames.Contains("Visibility"))
                throw new Exception("MCP catalog does not expose paid network upgrades correctly.");
            var createGroup=await Rpc(40,"tools/call",new { name="command",arguments=new {
                requestId=Guid.NewGuid().ToString(),expectedRevision=networkSnapshot.Snapshot.Revision,kind="CreateGroup",value=0,reason="MCP group check",
                name="Expedition",task="collect meat",objectiveX=40000,objectiveY=32000 } });
            if(createGroup.TryGetProperty("isError",out var groupError) && groupError.GetBoolean()) throw new Exception(createGroup.ToString());
            var groupSnapshot=(await new PipeClient(pipeName).SendAsync(new(Protocol.Version,"observe"))).Snapshot!;
            if(groupSnapshot.Groups.Length!=1 || groupSnapshot.Groups[0].Objective.X!=40000 || groupSnapshot.FoodTypes.Length!=8)
                throw new Exception("MCP group points or typed food did not round-trip.");
            await Rpc(41,"tools/call",new {name="command",arguments=new {requestId=Guid.NewGuid().ToString(),expectedRevision=groupSnapshot.Revision,
                kind="AssignAnt",value=0,reason="MCP assignment",groupId=1,antId=1} });
            var assigned=(await new PipeClient(pipeName).SendAsync(new(Protocol.Version,"observe"))).Snapshot!;
            await Rpc(42,"tools/call",new {name="command",arguments=new {requestId=Guid.NewGuid().ToString(),expectedRevision=assigned.Revision,
                kind="ApplyProgram",value=0,reason="MCP shared code",species="scout",programSource="memory[0]=42; wait();"} });
            var queued=(await new PipeClient(pipeName).SendAsync(new(Protocol.Version,"observe"))).Snapshot!;
            await Rpc(43,"tools/call",new {name="command",arguments=new {requestId=Guid.NewGuid().ToString(),expectedRevision=queued.Revision,
                kind="Step",value=0,reason="activate group code"} });
            var grouped=(await new PipeClient(pipeName).SendAsync(new(Protocol.Version,"observe"))).Snapshot!;
            if(grouped.Ants.Single(a=>a.Id==1).Memory[0]!=42 || grouped.Programs.Any(p=>p.GroupId!=0)) throw new Exception("MCP shared species code did not execute.");
            await Rpc(44,"tools/call",new {name="command",arguments=new {requestId=Guid.NewGuid().ToString(),expectedRevision=grouped.Revision,
                kind="SetGroupParameter",value=3,reason="custom agent setting",groupId=1,key="retreat_threshold"} });
            var inspected=await Rpc(45,"tools/call",new {name="inspect_group",arguments=new {groupId=1}});
            var groupText=inspected.GetProperty("content")[0].GetProperty("text").GetString()!;
            if(JsonDocument.Parse(groupText).RootElement.GetProperty("group").GetProperty("Parameters").GetProperty("retreat_threshold").GetInt32()!=3)
                throw new Exception("Named group parameters did not round-trip through real MCP.");
            Console.WriteLine("PASS real STDIO MCP manages groups and custom parameters while all groups share species code");
            Console.WriteLine("PASS real STDIO MCP network command shares budget checks and retires direct range control");
            Console.WriteLine("PASS real STDIO MCP upgrades hauler batch capacity");
            Console.WriteLine("PASS real STDIO MCP produces generic eggs and hatches selected species");
            Console.WriteLine("PASS real STDIO MCP initialize / observe / command / species program update → live host Tick 2");
            // 中文分组名真实 STDIO 往返：必须让中文以未转义的 UTF-8 字节进 MCP stdin
            // （模拟 scripts/game-agent.py 的 ensure_ascii=False），否则 \uXXXX 转义全是 ASCII、绕过编码验证。
            // 成功时世界状态里的 Groups 应含完整中文名；不新增 Check 计数，保持 460 口径。
            const string chineseName = "施工补给组-甲";
            var relaxed = new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
            async Task<JsonElement> RpcUtf8<T>(int id, T payload) {
                await mcp.StandardInput.WriteLineAsync(JsonSerializer.Serialize(payload, relaxed));
                while (true) {
                    var line = await mcp.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(15)) ?? throw new Exception("MCP exited.");
                    var message = JsonDocument.Parse(line).RootElement.Clone();
                    if (!message.TryGetProperty("id", out var responseId) || responseId.GetInt32() != id) continue;
                    if (message.TryGetProperty("error", out _)) throw new Exception(message.ToString());
                    return message.GetProperty("result");
                }
            }
            var chineseBefore = (await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"))).Snapshot!;
            var chineseResult = await RpcUtf8(46, new {
                jsonrpc = "2.0", id = 46, method = "tools/call",
                @params = new { name = "command", arguments = new {
                    requestId = Guid.NewGuid().ToString(), expectedRevision = chineseBefore.Revision,
                    kind = "CreateGroup", value = 0, reason = "MCP utf8 group name check",
                    name = chineseName, task = "搬运补给" } }
            });
            if (chineseResult.TryGetProperty("isError", out var chineseError) && chineseError.GetBoolean())
                throw new Exception(chineseResult.ToString());
            var chineseView = (await new PipeClient(pipeName).SendAsync(new(Protocol.Version, "observe"))).Snapshot;
            if (chineseView is null || !chineseView.Groups.Any(g => g.Name == chineseName))
                throw new Exception("Chinese group name did not round-trip through real STDIO MCP.");
            Console.WriteLine("PASS real STDIO MCP preserves a Chinese group name end to end (UTF-8, no BOM)");
        } finally {
            foreach (var process in new[] { mcp, host }) if (!process.HasExited) { process.Kill(true); await process.WaitForExitAsync(); }
        }
    }
}
