using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using AntMind.Contracts;

internal static class AgentMcpCheck {
    public static async Task Run(Action<bool,string> check) {
        var pipe="antmind-events-mcp-"+Guid.NewGuid().ToString("N");
        Process Start(string path,params string[] args) {
            var runtime=Path.GetFullPath(".tools/dotnet/dotnet.exe");
            var info=new ProcessStartInfo(File.Exists(runtime)?runtime:"dotnet") {UseShellExecute=false,CreateNoWindow=true,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardInputEncoding=new UTF8Encoding(false),StandardOutputEncoding=new UTF8Encoding(false),StandardErrorEncoding=new UTF8Encoding(false)};
            info.ArgumentList.Add(Path.GetFullPath(path));foreach(var arg in args)info.ArgumentList.Add(arg);info.Environment["ANTMIND_PIPE"]=pipe;
            return Process.Start(info)??throw new Exception("Failed to start MCP test process");
        }
        using var host=Start("tools/AntMind.Evaluator/bin/Debug/net10.0/AntMind.Evaluator.dll","--serve");using var mcp=Start("src/AntMind.Mcp/bin/Debug/net10.0/AntMind.Mcp.dll");
        _=host.StandardError.ReadToEndAsync();_=mcp.StandardError.ReadToEndAsync();
        var pending=new ConcurrentDictionary<int,TaskCompletionSource<JsonElement>>();var counter=0;using var writer=new SemaphoreSlim(1);
        var reader=Task.Run(async ()=>{
            while(await mcp.StandardOutput.ReadLineAsync() is {} line) {
                var root=JsonDocument.Parse(line).RootElement.Clone();
                if(root.TryGetProperty("id",out var id) && id.TryGetInt32(out var value) && pending.TryRemove(value,out var completion))completion.TrySetResult(root);
            }
            foreach(var completion in pending.Values)completion.TrySetException(new IOException("MCP closed"));
        });
        async Task Send(object message) {await writer.WaitAsync();try{await mcp.StandardInput.WriteLineAsync(JsonSerializer.Serialize(message));}finally{writer.Release();}}
        async Task<JsonElement> Rpc(string method,object parameters) {
            var id=Interlocked.Increment(ref counter);var completion=new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);pending[id]=completion;
            await Send(new {jsonrpc="2.0",id,method,@params=parameters});var response=await completion.Task.WaitAsync(TimeSpan.FromSeconds(15));
            if(response.TryGetProperty("error",out var error))throw new Exception(error.ToString());return response.GetProperty("result");
        }
        async Task<JsonElement> Tool(string name,object args) {
            var response=await Rpc("tools/call",new {name,arguments=args});
            if(response.TryGetProperty("isError",out var error) && error.GetBoolean())throw new Exception(response.ToString());
            return JsonDocument.Parse(response.GetProperty("content")[0].GetProperty("text").GetString()!).RootElement.Clone();
        }
        async Task<JsonElement> Summary()=>(await Tool("observe_summary",new {})).GetProperty("Summary");
        async Task<JsonElement> Command(string kind,int value=0,string key="") {
            var s=await Summary();return await Tool("command",new {requestId=Guid.NewGuid().ToString(),expectedRevision=s.GetProperty("Revision").GetInt64(),expectedWorldId=s.GetProperty("WorldId").GetString(),kind,value,key,reason="real event MCP regression"});
        }
        try {
            await Rpc("initialize",new {protocolVersion="2025-06-18",capabilities=new {},clientInfo=new {name="agent-event-mcp-check",version="1"}});
            await Send(new {jsonrpc="2.0",method="notifications/initialized"});
            var tools=await Rpc("tools/list",new {});var names=tools.GetProperty("tools").EnumerateArray().Select(x=>x.GetProperty("name").GetString()).ToHashSet();
            check(new[]{"watch_events","read_events","observe_summary","configure_group","preview_program","preview_program_batch"}.All(names.Contains) && names.Count==15,"real MCP advertises all Agent tools including whole-species preflight with valid schemas");
            var first=await Summary();var world=first.GetProperty("WorldId").GetString()!;
            var original=await Tool("observe",new {});
            check(JsonSerializer.Serialize(first).Length<JsonSerializer.Serialize(original).Length/2 && !first.TryGetProperty("Programs",out _),"real compact observation is substantially smaller and excludes program history");
            var watched=await Tool("watch_events",new {worldId=world,action="upsert",id="stock-test",name="Spend alert",kinds=new[]{"stock_below"},stockItem="fruit",stockThreshold=90});
            check(watched.GetProperty("Watches").GetProperty("Error").ValueKind==JsonValueKind.Null && (await Summary()).GetProperty("Revision").GetInt64()==first.GetProperty("Revision").GetInt64(),"real MCP registers monitors without changing world revision");
            var waiting=Tool("read_events",new {worldId=world,watchId="stock-test",after=0,timeoutSeconds=3});
            await Task.Delay(100);var stopwatch=Stopwatch.StartNew();var produced=await Command("ProduceEgg");
            check(produced.GetProperty("Result").GetProperty("Accepted").GetBoolean() && stopwatch.Elapsed<TimeSpan.FromSeconds(2),"a waiting event tool does not block another MCP command or the game actor");
            var eventPage=(await waiting).GetProperty("Events");
            check(eventPage.GetProperty("Items").EnumerateArray().Single().GetProperty("Kind").GetString()=="stock_below","real MCP wakes an awaiting Agent when its watched condition becomes true");
            var cursor=eventPage.GetProperty("Cursor").GetInt64();stopwatch.Restart();
            var timeout=(await Tool("read_events",new {worldId=world,watchId="stock-test",after=cursor,timeoutSeconds=1})).GetProperty("Events");
            check(timeout.GetProperty("Items").GetArrayLength()==0 && stopwatch.Elapsed>=TimeSpan.FromMilliseconds(800) && stopwatch.Elapsed<TimeSpan.FromSeconds(3),"event waits return a bounded empty timeout instead of hanging indefinitely");
            var beforePreview=await Summary();var preview=(await Tool("preview_program",new {species="scout",antId=1,source="memory[0]=88;set_target(12345,23456);"})).GetProperty("Preview");
            check(preview.GetProperty("Target").GetProperty("X").GetInt32()==12345 && (await Summary()).GetProperty("Revision").GetInt64()==beforePreview.GetProperty("Revision").GetInt64(),"real MCP previews a destination program without installing or executing it in the world");
            var meal=(await Tool("preview_program",new {species="scout",antId=1,source="eat_from(42,food_fruit);"})).GetProperty("Preview");
            check(meal.GetProperty("EatHolderId").GetInt32()==42 && meal.GetProperty("EatFood").GetString()=="fruit" && (await Summary()).GetProperty("Revision").GetInt64()==beforePreview.GetProperty("Revision").GetInt64(),"real MCP preview exposes explicit meal source and food without consuming anything or claiming physical reachability");
            var batch=(await Tool("preview_program_batch",new {species="scout",source="if(ant_id==1){wait();}else{repeat 16{memory[0]=memory[0]+1;}}"})).GetProperty("PreviewBatch");
            check(batch.GetProperty("AntCount").GetInt32()==5 && batch.GetProperty("EvaluatedDecisions").GetInt32()==10 && !batch.GetProperty("Passed").GetBoolean() && batch.GetProperty("FailedAntIds").GetArrayLength()==4 && (await Summary()).GetProperty("Revision").GetInt64()==beforePreview.GetProperty("Revision").GetInt64(),"real MCP whole-species preflight catches errors outside the first ant and changes no revision");
            var setup=await Tool("configure_group",new {requestId=Guid.NewGuid().ToString(),expectedRevision=beforePreview.GetProperty("Revision").GetInt64(),expectedWorldId=world,name="Atomic route",task="Public test",antIds=new[]{1,6},reason="test complete configuration",rallyX=65000,rallyY=64000,retreatX=63000,retreatY=64000,parameters=new {source=1,to=0},points=new {take=new {X=69000,Y=64000},drop=new {X=64000,Y=64000}}});
            check(setup.GetProperty("Result").GetProperty("Accepted").GetBoolean() && (await Summary()).GetProperty("Groups").EnumerateArray().Single().GetProperty("Pending").GetInt32()==2,"real MCP accepts structured point/parameter objects and exposes task acknowledgement state");
            var all=await Tool("observe",new {});var group=all.GetProperty("Snapshot").GetProperty("Groups")[0];
            check(group.GetProperty("Points").GetProperty("take").GetProperty("X").GetInt32()==69000 && group.GetProperty("Parameters").GetProperty("source").GetInt32()==1 && group.GetProperty("Rally").GetProperty("X").GetInt32()==65000 && group.GetProperty("Retreat").GetProperty("X").GetInt32()==63000,"atomic MCP configuration preserves rally, retreat, named coordinates and arbitrary group data");
            await Command("Step");check((await Summary()).GetProperty("Groups")[0].GetProperty("Acknowledged").GetInt32()==2,"the same MCP-configured members acknowledge only after their programs request queen information");
        } finally {
            foreach(var child in new[]{mcp,host})if(!child.HasExited){child.Kill(true);await child.WaitForExitAsync();}
            await reader;
        }
    }
}
