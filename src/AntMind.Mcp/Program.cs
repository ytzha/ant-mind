using System.ComponentModel;
using System.Collections.Immutable;
using System.Text.Json;
using AntMind.Contracts;
using AntMind.Transport;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using ModelContextProtocol.Server;
using ModelContextProtocol.Protocol;
Console.InputEncoding = new System.Text.UTF8Encoding(false);
Console.OutputEncoding = new System.Text.UTF8Encoding(false);
var builder = Host.CreateApplicationBuilder(args);
builder.Logging.AddConsole(options => options.LogToStandardErrorThreshold = LogLevel.Trace);
builder.Services.AddSingleton(new PipeClient(Environment.GetEnvironmentVariable("ANTMIND_PIPE") ?? "antmind-v1"));
builder.Services.AddSingleton<AgentLink>();
builder.Services.AddHostedService(provider => provider.GetRequiredService<AgentLink>());
builder.Services.AddMcpServer().WithStdioServerTransport().WithToolsFromAssembly()
    .WithMessageFilters(filters => filters.AddIncomingFilter(next => async (context, ct) => {
        await next(context, ct);
        if (context.JsonRpcMessage is JsonRpcNotification { Method: "notifications/initialized" } && context.Server.ClientInfo is { } info)
            await context.Services!.GetRequiredService<AgentLink>().InitializeAsync(info.Name, ct);
    }));
await builder.Build().RunAsync();
[McpServerToolType]
public sealed class GameTools(PipeClient client) {
    [McpServerTool(Name="observe_summary",ReadOnly=true,Destructive=false,OpenWorld=false),Description("Read compact colony economy, danger/problem ants, known enemy reports, building material needs and group task acknowledgement versions. Omits program sources/history and memories; obeys discovery permissions.")]
    public async Task<string> Summary(CancellationToken cancellationToken)=>JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version,"summary"),cancellationToken));

    [McpServerTool(Name="watch_events",Destructive=false,Idempotent=true,OpenWorld=false),Description("Configure/list/remove session event watches. A null center follows the queen; radiusCells uses a circle. Enemy alerts use only actually observed positions, never unknown enemies. Kinds: enemy_seen, enemy_entered_zone, enemy_defeated, queen_attacked, ant_attacked, ant_died, building_ready, production_completed, task_received, program_error, program_recovered, action_failed, stock_below. Watches retain events while the game session lives; they do not make an AI run after its task ends. Use worldId from observe_summary, then read_events with a cursor.")]
    public async Task<string> Watch(string worldId,CancellationToken cancellationToken,string action="list",string id="",string name="Agent watch",string[]? kinds=null,int radiusCells=8,int? centerX=null,int? centerY=null,int groupId=0,string species="",int failureThreshold=3,string stockItem="fruit",long stockThreshold=0,bool fireInitial=true) {
        if(centerX.HasValue!=centerY.HasValue)throw new ArgumentException("Supply both center coordinates.");
        var definition=action=="upsert"?new AgentWatch(id,name) {Kinds=kinds?.ToImmutableArray()??AgentEventKinds.Defaults,Center=centerX is {} x?new Point(x,centerY!.Value):null,RadiusCells=radiusCells,GroupId=groupId,Species=species,FailureThreshold=failureThreshold,StockItem=stockItem,StockThreshold=stockThreshold,FireInitial=fireInitial}:null;
        return JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version,"watch",Watch:new(Guid.Parse(worldId),action,definition,id)),cancellationToken));
    }
    [McpServerTool(Name="read_events",ReadOnly=true,Destructive=false,OpenWorld=false),Description("Read event pages after a sequence, optionally wait 0..30 seconds for a matching alert. Waiting never blocks simulation, commands or heartbeat. Pass observed worldId; world_conflict after load requires re-observing and registering watches. Cursor/Gap/HasMore describe replay and bounded retention. Each watch/filter needs its own cursor. Timeout returns an empty page, not a perpetual AI service.")]
    public async Task<string> Events(string worldId,CancellationToken cancellationToken,long after=0,string watchId="",int limit=50,int timeoutSeconds=0) {
        if(timeoutSeconds is <0 or >30)throw new ArgumentException("timeoutSeconds must be 0..30.");
        var until=System.Diagnostics.Stopwatch.StartNew();WireResponse result;
        do {
            result=await client.SendAsync(new(Protocol.Version,"events",Events:new(Guid.Parse(worldId),after,watchId,limit)),cancellationToken);
            if(result.Error is not null || result.Events is not {} page || page.Error is not null || page.Gap || page.Items.Length>0 || until.Elapsed.TotalSeconds>=timeoutSeconds)break;
            await Task.Delay(TimeSpan.FromMilliseconds(Math.Min(250,Math.Max(1,timeoutSeconds*1000-until.ElapsedMilliseconds))),cancellationToken);
        }while(true);
        return JsonSerializer.Serialize(result);
    }
    [McpServerTool(Name="configure_group",Destructive=false,Idempotent=true,OpenWorld=false),Description("Atomically create (groupId=0) or replace a complete group configuration and exact membership in one revision. Retained members keep behavior and cached old orders until an explicit queen request; changed members reset behavior. All ants still share species code. Invalid members/fields change nothing; retry a requestId only with identical fields. Points are fixed-point objects {X,Y}; keys are arbitrary, up to 64 parameters/16 points.")]
    public async Task<string> ConfigureGroup(string requestId,long expectedRevision,string expectedWorldId,string name,string task,int[] antIds,string reason,CancellationToken cancellationToken,int groupId=0,string activity="collect",string foodFilter="",int radiusCells=8,Dictionary<string,int>? parameters=null,Dictionary<string,Point>? points=null,int? objectiveX=null,int? objectiveY=null,int? rallyX=null,int? rallyY=null,int? retreatX=null,int? retreatY=null) {
        if(objectiveX.HasValue!=objectiveY.HasValue)throw new ArgumentException("Supply both objective coordinates.");
        if(rallyX.HasValue!=rallyY.HasValue || retreatX.HasValue!=retreatY.HasValue)throw new ArgumentException("Supply both coordinates of rally and retreat points.");
        var setup=new GroupConfiguration(name,task) {Members=antIds.ToImmutableArray(),Parameters=parameters?.ToImmutableDictionary(StringComparer.Ordinal)??ImmutableDictionary<string,int>.Empty,Points=points?.ToImmutableDictionary(StringComparer.Ordinal)??ImmutableDictionary<string,Point>.Empty,
            Activity=activity,FoodFilter=foodFilter,RadiusCells=radiusCells,Objective=objectiveX is {} x?new Point(x,objectiveY!.Value):null,
            Rally=rallyX is {} rx?new Point(rx,rallyY!.Value):null,Retreat=retreatX is {} tx?new Point(tx,retreatY!.Value):null};
        return JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version,"command",new(Guid.Parse(requestId),expectedRevision,CommandKind.ConfigureGroup,Reason:reason) {ExpectedWorldId=Guid.Parse(expectedWorldId),GroupId=groupId,GroupConfiguration=setup}),cancellationToken));
    }
    [McpServerTool(Name="preview_program",ReadOnly=true,Destructive=false,OpenWorld=false),Description("Compile and execute one candidate species program once using a living ant's actual permitted perception and current budget. Returns intent, target, instruction cost, proposed memory and errors; changes no position, memory, RNG, program versions or world revision. AntId=0 picks the first living ant of the species.")]
    public async Task<string> Preview(string species,string source,CancellationToken cancellationToken,int antId=0)=>JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version,"preview_program",Preview:new(species,source,antId)),cancellationToken));

    [McpServerTool(Name="preview_program_batch",ReadOnly=true,Destructive=false,OpenWorld=false),Description("Preflight a candidate against EVERY living ant of one species, sorted by ID, at one actor-consistent revision. Each ant is checked in current state AND fresh program-activation state (memory/target/work/healing reset exactly as ApplyProgram). Returns per-ant decisions, maximum sampled budget and failed IDs. Compiles once and changes no world, memory, RNG, program, events or revision. Passed covers these decisions only; no future states or physical outcomes are simulated.")]
    public async Task<string> PreviewBatch(string species,string source,CancellationToken cancellationToken)=>JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version,"preview_program_batch",Preview:new(species,source)),cancellationToken));

    [McpServerTool(Name = "get_actions"), Description("List every callable game command, including all available simulation buttons.")]
    public string GetActions() => JsonSerializer.Serialize(new {
        events="observe_summary gives compact state and EventCursor. watch_events configures session monitors. read_events(worldId, after, watchId, timeoutSeconds<=30) waits without revealing unknown enemies. Program faults notify immediately, then append aggregate batches at most every 200 simulation ticks; Count/FirstTick/LastTick/ProgramVersion describe each immutable batch. program_recovered follows 200 error-free ticks and a successful decision. History is bounded with Gap/cursor pagination. configure_group is atomic. preview_program checks one current ant; preview_program_batch checks ALL living ants of one species in current and fresh-activation states at one revision, with failed IDs/max sampled budget. No future simulation or mutation. Watches/history reset on load. No permanently running model is implied.",
        production="TechnologyLevel equals NetworkLevel; workshop is the kitchen (Lv2), chef Lv2; recipes at levels 2/3/4/5. Recipe ExtraInputs adds mixed ingredients; all inputs must be physically present. PlanBuild(key=cache|workshop,pointX/Y,reason) creates a free blueprint, at least 2 cells from the queen and other active sites. New plans use wood (MaterialType/MaterialCost); only BuilderSpecies can construct, default builder. Wood sources slowly regrow. Legacy fiber sites retain ConstructionItem=fiber. CancelBuild(value=buildingId) retains physical materials. DSL harvest(sourceId,qty), deposit(holderId,itemCode,qty), withdraw, transfer(antId,itemCode,qty), process(station,recipeCode), work(station). eat_from(holderId,itemCode) explicitly channels a 40-Tick meal from nest (0) or a ready CanFeedAnts building, consuming exactly one local portion at completion and interrupting on damage. Cache is now a supply outpost, still a stable storage endpoint for future transport. nearest_supply_id/x/y/distance/food and building_can_feed(id) use local perception only; default guards seek visible supplied outposts when safe. Holder 0 is nest. source/building_* read local observations only. Chef uses group station/recipe parameters and objective; Only builder can work on blueprints; all species can process ready stations, chef rate 2. Builder uses group station parameter and objective; logistics are still explicit. get_catalog lists stable definitions, inspect_object also accepts source/building. Inventory excludes nonfood wood/fiber. FirstAdmissionPoints counts new raw food once; Economy reports simulated-minute rates.",
        movement="DSL set_target(x,y) assigns an absolute fixed-point destination (1000 units/cell). The engine moves continuously towards it in any direction at the actual load/rank speed cap, until reached or another physical action replaces it. No per-axis stepping required. has_target/target_x/target_y/target_distance/target_reached query the current destination; wait() stops and clears it. move_to(x,y) remains a compatible alias. Arrival does not automatically collect/deliver/work. Directions use deterministic integer vector movement, including enemies and follow.",
        saves="SaveGame(key=slot,reason), LoadGame(key=slot,reason). Load is paused, restores world/RNG/memory/programs and changes WorldId; ALWAYS pass expectedWorldId from observe to command. list_saves returns metadata only.",
        veterancy="Each ant has independent Level 1..3, Experience, CompletedWork and work remainders; AntLevels lists thresholds and bonuses. XP comes from first exploration, harvesting, first admissions, effective labor and combat, not repeated cargo loops. DSL ant_level/experience/experience_to_next reads own state. Local debug console reuses the same commands and discovery projection.",
        protocolVersion = Protocol.Version, commands = Enum.GetNames<CommandKind>().Where(x => x != nameof(CommandKind.ClearGroupProgram) && x != nameof(CommandKind.Visibility) && x != nameof(CommandKind.Recruit) && x != nameof(CommandKind.SetQueenRange)),
        network = "UpgradeNetwork(reason): spend food to raise the shared technology level; range and technology unlocks are derived from this level. SetQueenRange is retired. Observe NetworkLevel, NextNetworkRangeCells, NextNetworkUpgradeCost and Technologies.", minimumReserveValues = "0..1000000000", populationCapValues = "current population..100",
        speedValues = new[] {1, 2, 5}, visibilityValues = new[] {"Discovered only; hidden food cannot be revealed"},
        species = new[] {"scout", "hauler", "soldier", "chef", "builder"},
        workflow = "observe; command with observed revision and new UUID requestId; identical retries reuse UUID",
        carryUpgrade = "UpgradeCarry(species=hauler,reason); applies to all existing and future haulers; observe species for current capacity and next cost",
        eggs = "ProduceEgg(reason): one generic egg; HatchEgg(species,reason): one egg becomes one ant without another resource charge; population cap applies at hatching",
        program = "ApplyProgram(species,programSource,reason); RollbackProgram(species,value=version,reason). All groups share the species code. Nonzero groupId is rejected for program operations.",
        groups = "CreateGroup and UpdateGroup accept name,task, arbitrary activity label, optional foodFilter, objectiveX/Y and radiusCells. AssignAnt(groupId,antId) or atomic AssignAnts(groupId,antIds); 0 removes membership. SetGroupParameter(groupId,key,value), RemoveGroupParameter(groupId,key), SetGroupPoint(groupId,key,pointX,pointY), RemoveGroupPoint(groupId,key), DeleteGroup(groupId). All require reason. 64 arbitrary integer parameters and 16 named points per group. inspect_group reads group and members. Shared species DSL reads param(quoted_key), has_param, group_x, group_y, has_point from explicitly requested queen cache; no group-specific code. Coordinates use 1000 units/cell.",
        food = "Stock is per-type inventory, FoodTypes defines IDs, per-item Value and heal amounts. DevelopmentValue = stored edible value + DevelopmentChange; upgrades/reserve use value points. Whole-item overpayment is retained as change. Inventory remains physical portions; ProcessingValueAdded counts actual completed-recipe profit once.  Natural food is fruit; carcasses are meat; cargo CarryFood is preserved. eat_from(stationId,itemCode) uses ready outpost stock without cargo or remote-nest fallback; outpost supplies are independent of nest minimum reserve. eat(food_fruit|food_meat) consumes one portion after 40 uninterrupted ticks; nest stock respects reserve. Follow(id,distance) and claim_food(id,quantity,ttl) are explicit DSL actions; claims are advisory and local.",
        combat = "Soldiers use explicit attack(enemy_id); nearest_enemy_* only senses local enemies. Defeated enemies become movable carcass food. Queen death stops the colony.",
        queen = "request_queen_info() and report_discovery() are explicit DSL actions; queen_* data is a cached reply, updated only after a successful in-range request"
    });
    [McpServerTool(Name="evaluate_save"),Description("Compare two isolated continuations of one save with identical world/RNG. Optional candidate species/source replaces that shared species code. No live world changes; 1..1200 ticks; prefer 1200.")]
    public async Task<string> EvaluateSave(string slot,int ticks,CancellationToken cancellationToken,string species="",string source="")=>JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version,"evaluate_save",Evaluation:new(slot,ticks,species,source)),cancellationToken));
    [McpServerTool(Name="get_catalog"), Description("Read public item, recipe, building and species definitions, without hidden world locations.")]
    public async Task<string> Catalog(CancellationToken cancellationToken) {var r=await client.SendAsync(new(Protocol.Version,"observe"),cancellationToken);return JsonSerializer.Serialize(new {r.Error,AntLevels=r.Snapshot?.AntLevels,TechnologyLevel=r.Snapshot?.TechnologyLevel,TechnologyEra=r.Snapshot?.TechnologyEra,TechnologyEras=r.Snapshot?.TechnologyEras,Unlocks=r.Snapshot?.Technologies,DevelopmentValue=r.Snapshot?.DevelopmentValue,Items=r.Snapshot?.FoodTypes,Recipes=r.Snapshot?.Recipes,Buildings=r.Snapshot?.BuildingTypes,Species=r.Snapshot?.Species});}
    [McpServerTool(Name="list_saves"),Description("List save-slot metadata only; saved hidden objects are never returned.")]
    public async Task<string> Saves(CancellationToken cancellationToken)=>JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version,"list_saves"),cancellationToken));
    [McpServerTool(Name = "validate_program"), Description("Validate bounded ant DSL without changing the world.")]
    public string ValidateProgram(string source) {
        try { AntMind.Programs.AntDslCompiler.Compile(source); return "{\"valid\":true}"; }
        catch (FormatException error) { return JsonSerializer.Serialize(new { valid = false, error = error.Message }); }
    }
    [McpServerTool(Name = "inspect_object"), Description("Read one independent object record by kind=ant, food, queen, enemy, source or building and ID. Undiscovered food returns object_not_found, exactly like a nonexistent ID.")]
    public async Task<string> InspectObject(string kind, int id, CancellationToken cancellationToken) =>
        JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version, "inspect_object", ObjectKind: kind, ObjectId: id), cancellationToken));
    [McpServerTool(Name = "inspect_group"), Description("Read a group's task data, arbitrary parameters, named points and living members. Groups have no independent code; all members use species programs.")]
    public async Task<string> InspectGroup(int groupId,CancellationToken cancellationToken) {
        var response=await client.SendAsync(new(Protocol.Version,"observe"),cancellationToken);
        var group=response.Snapshot?.Groups.FirstOrDefault(g=>g.Id==groupId);
        return JsonSerializer.Serialize(new { protocolVersion=Protocol.Version,group,
            members=response.Snapshot?.Ants.Where(a=>a.GroupId==groupId).ToArray(),error=group is null?response.Error??"group_not_found":null });
    }
    [McpServerTool(Name = "observe"), Description("Read the live colony with discovered food only, including ant species definitions, counts, delivery statistics and milestone progress/status/deadlines. Never returns the player's unrestricted map.")]
    public async Task<string> Observe(CancellationToken cancellationToken) =>
        JsonSerializer.Serialize(await client.SendAsync(new(Protocol.Version, "observe"), cancellationToken));
    [McpServerTool(Name = "command"), Description("Apply group management CreateGroup, UpdateGroup, DeleteGroup, AssignAnt, or Pause, Resume, Step, Speed, ProduceEgg, HatchEgg, UpgradeCarry, UpgradeBrain, UpgradeNetwork, ApplyProgram or RollbackProgram. ProduceEgg spends resources to create one generic egg; HatchEgg consumes one egg and selects species=scout, species=hauler or species=soldier. Recruit is retired. ApplyProgram supplies bounded DSL text in programSource; activation waits for the next simulation Tick. RollbackProgram uses value as the target version and also activates at a Tick boundary. Spending and program changes require a reason. Supply the observed revision and a stable UUID requestId; retry with identical fields. Visibility switching is retired: both player and Agent only see discovered food.")]
    public async Task<string> Command(string requestId, long expectedRevision, string kind, int value,
        string reason, CancellationToken cancellationToken, string species = AntSpeciesIds.Scout,
        string programSource = "", int groupId=0, int antId=0, string name="", string task="",
        int? rallyX=null,int? rallyY=null,int? objectiveX=null,int? objectiveY=null,int? retreatX=null,int? retreatY=null, string? activity=null,string? foodFilter=null,int? radiusCells=null, int[]? antIds=null,string key="",int? pointX=null,int? pointY=null,string? expectedWorldId=null) {
        Point? Pair(int? x,int? y) => x.HasValue==y.HasValue ? x.HasValue?new Point(x.Value,y!.Value):null : throw new ArgumentException("Supply both coordinates.");
        if (!Enum.TryParse<CommandKind>(kind, false, out var parsed)) throw new ArgumentException("Unknown command kind.");
        return JsonSerializer.Serialize(await client.SendAsync(
            new(Protocol.Version, "command", new(Guid.Parse(requestId), expectedRevision, parsed, value,
                reason, species, programSource) { ExpectedWorldId=expectedWorldId is null?null:Guid.Parse(expectedWorldId),GroupId=groupId,AntId=antId,AntIds=antIds?.ToImmutableArray()??[],Key=key,Location=Pair(pointX,pointY),Name=name,Task=task,Activity=activity,FoodFilter=foodFilter,RadiusCells=radiusCells,Rally=Pair(rallyX,rallyY),Objective=Pair(objectiveX,objectiveY),Retreat=Pair(retreatX,retreatY) }), cancellationToken));
    }
}
