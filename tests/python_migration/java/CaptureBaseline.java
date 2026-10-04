import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import org.junit.runner.JUnitCore;
import org.junit.runner.Result;
import org.junit.runner.Request;
import org.junit.runner.Description;
import org.junit.runner.manipulation.Filter;
import org.junit.runner.notification.Failure;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.http.converter.json.Jackson2ObjectMapperBuilder;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.RequestMappingInfo;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;
import org.wwz.ai.application.agent.query.IGptQueryApplicationService;
import org.wwz.ai.application.agent.stream.AgentSessionStream;
import org.wwz.ai.application.agent.stream.AgentResponseProjectionStream;
import org.wwz.ai.application.agent.askuser.AskUserQuestionApplicationService;
import org.wwz.ai.domain.agent.runtime.GptQueryAgentRequestFactory;
import org.wwz.ai.domain.agent.runtime.ReactorRuntimeDependencies;
import org.wwz.ai.domain.agent.runtime.agent.AgentContext;
import org.wwz.ai.domain.agent.runtime.askuser.*;
import org.wwz.ai.domain.agent.runtime.tool.*;
import org.wwz.ai.domain.agent.runtime.tool.common.canvas.*;
import org.wwz.ai.domain.agent.runtime.tool.factory.AgentToolCollectionFactory;
import org.wwz.ai.domain.agent.runtime.tool.mcp.runtime.McpToolExecutor;
import org.wwz.ai.domain.agent.runtime.tool.skill.*;
import org.wwz.ai.domain.agent.runtime.tool.workspace.*;
import org.wwz.ai.domain.agent.reactor.config.ReactorConfig;
import org.wwz.ai.domain.agent.reactor.model.req.*;
import org.wwz.ai.domain.agent.reactor.model.response.GptProcessResult;
import org.wwz.ai.domain.agent.runtime.dto.Message;
import org.wwz.ai.domain.agent.runtime.dto.tool.ToolCall;
import org.wwz.ai.domain.agent.runtime.planmode.*;
import org.wwz.ai.application.agent.planmode.PlanApprovalResumeApplicationService;
import org.wwz.ai.trigger.http.AiAgentController;
import org.wwz.ai.trigger.http.agent.AgentRunController;
import org.wwz.ai.trigger.http.agent.AgentGenUiExportController;
import org.wwz.ai.types.agent.config.AgentExecutorProperties;
import org.wwz.ai.types.agent.visitor.VisitorRequestContext;
import org.wwz.ai.infrastructure.dataquery.jdbc.connection.*;
import org.wwz.ai.infrastructure.dataquery.jdbc.JdbcConnectionConfig;
import org.wwz.ai.infrastructure.dataquery.jdbc.dialect.h2.H2DialectFactory;
import org.wwz.ai.infrastructure.dataquery.jdbc.dialect.JdbcDialectLoader;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.sql.*;
import java.util.*;
import java.util.stream.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.junit.Assert.*;

/** P0-only entry point. No Spring boot, application profiles, model or real DB. */
public class CaptureBaseline {
    static ObjectMapper json = Jackson2ObjectMapperBuilder.json().build();
    static Path root, output;
    static Map<String,Object> behavior = new TreeMap<>();
    static void write(String name,Object value) throws Exception {
        json.writerWithDefaultPrettyPrinter().writeValue(output.resolve(name).toFile(),value);
    }
    public static void main(String[] args) throws Exception {
        root=Path.of(args[0]); output=Path.of(args[1]);
        new org.springframework.boot.test.context.runner.ApplicationContextRunner()
            .withConfiguration(org.springframework.boot.autoconfigure.AutoConfigurations.of(org.springframework.boot.autoconfigure.jackson.JacksonAutoConfiguration.class))
            .run(context -> json=context.getBean(ObjectMapper.class));
        List<Map<String,Object>> results=new ArrayList<>(); int count=0, errors=0;
        for(int i=2;i<args.length;i++) {
            Request request=Request.aClass(Class.forName(args[i]));
            if(args[i].endsWith("AgentToolCollectionFactoryTest")) request=request.filterWith(new Filter(){
                public boolean shouldRun(Description d){return !"deployedPlanSolveMainToolListIncludesTaskOutputAndSendMessage".equals(d.getMethodName());}
                public String describe(){return "Exclude deployment-profile assertion requiring unbundled application-dev.yml; other eleven isolated factory tests run";}
            });
            Result r=new JUnitCore().run(request); count+=r.getRunCount(); errors+=r.getFailureCount();
            results.add(Map.of("class",args[i],"tests",r.getRunCount(),"failures",r.getFailureCount(),"ignored",r.getIgnoreCount(),
                "excluded",args[i].endsWith("AgentToolCollectionFactoryTest") ? List.of("deployedPlanSolveMainToolListIncludesTaskOutputAndSendMessage: missing application-dev.yml; deployment validation U") : List.of(),"details",r.getFailures().stream().map(Failure::toString).toList()));
        }
        write("test-results.json",Map.of("tests",count,"failures",errors,"classes",results));
        if(errors>0)throw new AssertionError("Selected baseline tests failed: "+errors);
        captureRoutes(); captureTools(); captureHttp(); captureSerialization(); captureHitl(); captureH2(); captureSql(); captureHistory();
        write("java-behavior.json",behavior);
    }
    static List<String> classes(String module) throws Exception {
        Path src=root.resolve(module+"/src/main/java");
        try(Stream<Path> files=Files.walk(src)) {
            return files.filter(p->p.toString().endsWith(".java")).map(p->src.relativize(p).toString().replace('/', '.').replace(".java", "")).sorted().toList();
        }
    }
    static class MappingReader extends RequestMappingHandlerMapping {
        RequestMappingInfo read(Method method,Class<?> type){return getMappingForMethod(method,type);}
    }
    static void captureRoutes() throws Exception {
        MappingReader mapping=new MappingReader(); List<Map<String,Object>> routes=new ArrayList<>();
        for(String name:classes("Reactor-agent-trigger")) {
            Class<?> type=Class.forName(name);
            if(!type.isAnnotationPresent(RestController.class))continue;
            for(Method method:type.getDeclaredMethods()) {
                RequestMappingInfo info=mapping.read(method,type); if(info==null)continue;
                List<Map<String,Object>> params=new ArrayList<>();
                for(Parameter p:method.getParameters()) params.add(Map.of("type",p.getParameterizedType().getTypeName(),"annotations",Arrays.stream(p.getAnnotations()).map(Object::toString).sorted().toList()));
                routes.add(Map.of("controller",name,"method",method.getName(),"paths",info.getPatternValues().stream().sorted().toList(),
                    "verbs",info.getMethodsCondition().getMethods().stream().map(Object::toString).sorted().toList(),
                    "produces",info.getProducesCondition().getProducibleMediaTypes().stream().map(Object::toString).sorted().toList(),
                    "consumes",info.getConsumesCondition().getConsumableMediaTypes().stream().map(Object::toString).sorted().toList(),
                    "parameters",params,"returnType",method.getGenericReturnType().getTypeName(),"evidence","java-reflection-mapping"));
            }
        }
        routes.sort(Comparator.<Map<String,Object>,String>comparing(r->r.get("controller")+":"+r.get("method")).thenComparing(r->r.get("paths").toString()));
        assertEquals("Audited route count drift",108,routes.size()); write("runtime-routes.json",routes);
    }
    static Object invokePrivate(Object target,String name,Object... args) throws Exception {
        Method method=Arrays.stream(target.getClass().getDeclaredMethods()).filter(m->m.getName().equals(name)).findFirst().orElseThrow();
        method.setAccessible(true);return method.invoke(target,args);
    }
    static void captureTools() throws Exception {
        Object helper=Class.forName("org.wwz.ai.test.spring.ai.AgentToolCollectionFactoryTest").getConstructor().newInstance();
        ReactorConfig config=new ReactorConfig(); config.setMultiAgentToolList("{\"default\":\"search,web_fetch,web_search,code_execution,docgen,docread,dataprep,canvas,image_generation,data_analysis,twitter,reddit,xueqiu\"}");
        config.setMcpToolSearchMode("standard");
        McpToolExecutor mcp=Mockito.mock(McpToolExecutor.class);Mockito.when(mcp.discoverConfiguredTools()).thenReturn(List.of());
        DefaultSkillRegistry registry=(DefaultSkillRegistry)invokePrivate(helper,"createRegistry",true,true); registry.refresh();
        SkillRuntimeOptions skill=SkillRuntimeOptions.builder().enabled(true).reactEnabled(true).planSolveEnabled(true).sandboxBashEnabled(true).build();
        WorkspaceService workspace=(WorkspaceService)invokePrivate(helper,"enabledWorkspaceService");
        WorkspaceRuntimeOptions opts=(WorkspaceRuntimeOptions)invokePrivate(helper,"enabledWorkspaceOptions");
        AgentToolCollectionFactory factory=(AgentToolCollectionFactory)invokePrivate(helper,"newFactory",config,mcp,registry,skill,workspace,opts);
        AgentContext context=(AgentContext)invokePrivate(helper,"buildAgentContext");
        context.setRuntimeDependencies(ReactorRuntimeDependencies.builder().reactorConfig(config).mcpToolExecutor(mcp)
                .curatedMemoryStore(Mockito.mock(org.wwz.ai.domain.agent.memory.ltm.CuratedMemoryStore.class))
                .sessionSearchService(Mockito.mock(org.wwz.ai.domain.agent.memory.ltm.SessionSearchService.class)).build());
        context.setWorkspaceRoot(System.getProperty("java.io.tmpdir")+"/workspace/session-p0");
        AgentRequest request=(AgentRequest)invokePrivate(helper,"buildAgentRequest",(Object)new String[]{"html"});
        ToolCollection full=factory.buildForReact(context,request);
        Map<String,Object> schemas=new TreeMap<>();
        for(BaseTool tool:full.getToolMap().values()) schemas.put(tool.getName(),Map.of("class",tool.getClass().getName(),"description",tool.getDescription(),"parameters",tool.toParams(),"evidence","java-factory-runtime"));
        // Also evaluate schemas of legacy/unmounted tool classes. Never execute remote tools.
        List<Map<String,Object>> unsupported=new ArrayList<>();
        for(String name:classes("Reactor-agent-domain")) {
            if(!name.contains(".runtime.tool."))continue;
            Class<?> type=Class.forName(name);
            if(type.isInterface()||Modifier.isAbstract(type.getModifiers())||!BaseTool.class.isAssignableFrom(type))continue;
            if(schemas.values().stream().anyMatch(v->((Map<?,?>)v).get("class").equals(name)))continue;
            if(type==ContextScopedTool.class){unsupported.add(Map.of("class",name,"evidence","covered-delegation","reason","wrapShared delegates name/description/schema; no separate wire tool"));continue;}
            try {
                BaseTool tool=(BaseTool)type.getConstructor().newInstance();
                try{type.getMethod("setAgentContext",AgentContext.class).invoke(tool,context);}catch(NoSuchMethodException ignored){}
                Map<String,Object> entry=new TreeMap<>();entry.put("class",name);entry.put("description",tool.getDescription());entry.put("parameters",tool.toParams());entry.put("evidence","java-schema-only-unmounted");schemas.put(tool.getName(),entry);
            } catch(Exception e){unsupported.add(Map.of("class",name,"reason",e.getClass().getSimpleName(),"evidence","unverified"));}
        }
        ToolCollection plan=factory.buildForPlanSolve(context,request);
        List<String> defaultMain=new ArrayList<>(factory.filterForPlanSolveMain(plan).getToolMap().keySet());
        config.setPlanSolveMainToolList("Agent,TaskCreate,TaskOutput,SendMessage,EnterPlanMode,ExitPlanMode,AskUserQuestion");
        List<String> configuredMain=new ArrayList<>(factory.filterForPlanSolveMain(plan).getToolMap().keySet());
        request.setOutputStyle("dataAgent");List<String> data=new ArrayList<>(factory.buildForReact(context,request).getToolMap().keySet());
        var discovered=org.wwz.ai.domain.agent.runtime.dto.tool.McpToolInfo.builder().mcpId("mcp-p0").serverKey("fixture").name("mcp__fixture__lookup").originalName("lookup").desc("isolated discovery fixture").parameters("{\"type\":\"object\",\"properties\":{\"q\":{\"type\":\"string\"}}}").alwaysLoad(false).build();
        Mockito.when(mcp.discoverConfiguredTools()).thenReturn(List.of(discovered));
        request.setOutputStyle(null);Map<String,Object> mcpProfiles=new TreeMap<>();
        config.setMcpToolSearchMode("standard");mcpProfiles.put("standard",factory.buildForReact(context,request).getMcpToolMap());
        config.setMcpToolSearchMode("always");ToolCollection deferred=factory.buildForReact(context,request);mcpProfiles.put("always-visible",deferred.getMcpToolMap());mcpProfiles.put("always-has-tool-search",deferred.getToolMap().containsKey("ToolSearch"));
        write("tool-schemas.json",Map.of("mcpProfiles",mcpProfiles,"profile","all-supported-groups; local test skills/workspace; no remote MCP", "schemas",schemas,
            "factoryReact",new ArrayList<>(full.getToolMap().keySet()),"factoryPlanSolve",new ArrayList<>(plan.getToolMap().keySet()),"planMainConfigured",configuredMain,"planMain",defaultMain,"dataAgent",data,"unsupported",unsupported));
    }
    static Map<String,Object> http(MockMvc mvc,MockHttpServletRequestBuilder input) throws Exception {
        MvcResult result=mvc.perform(input).andReturn();
        if(result.getRequest().isAsyncStarted()) {result.getAsyncResult(5000);result=mvc.perform(asyncDispatch(result)).andReturn();}
        var response=result.getResponse();String raw=response.getContentAsString(StandardCharsets.UTF_8);
        Map<String,Object> r=new LinkedHashMap<>();r.put("status",response.getStatus());r.put("contentType",response.getContentType());
        r.put("body",raw);return r;
    }
    static void captureHttp() throws Exception {
        AiAgentController query=new AiAgentController();
        IGptQueryApplicationService app=Mockito.mock(IGptQueryApplicationService.class);
        ReflectionTestUtils.setField(query,"gptQueryApplicationService",app);
        ReflectionTestUtils.setField(query,"heartbeatScheduler",Mockito.mock(TaskScheduler.class));
        ReflectionTestUtils.setField(query,"agentExecutorProperties",new AgentExecutorProperties());
        Mockito.doAnswer(call->{
            AgentSessionStream stream=call.getArgument(1);
            stream.send(AgentResponseProjectionStream.buildHeartbeat("req-p0"));
            stream.send(AgentResponseProjectionStream.buildFollowPending("req-p0",800L));
            stream.send(AgentResponseProjectionStream.buildFollowIdle("req-p0"));stream.complete();return null;
        }).when(app).queryAgentStreamIncr(Mockito.any(),Mockito.any());
        var dataController=new org.wwz.ai.trigger.http.dataagent.DataAgentController();
        var dataService=Mockito.mock(org.wwz.ai.application.agent.dataquery.IDataAgentApplicationService.class);
        ReflectionTestUtils.setField(dataController,"dataAgentApplicationService",dataService);
        Mockito.when(dataService.queryAllModelsWithSchema()).thenReturn(List.of());
        MockMvc mvc=MockMvcBuilders.standaloneSetup(query,new AgentRunController(),new AgentGenUiExportController(),dataController)
            .setMessageConverters(new org.springframework.http.converter.StringHttpMessageConverter(StandardCharsets.UTF_8),
                new org.springframework.http.converter.ByteArrayHttpMessageConverter(),
                new org.springframework.http.converter.json.MappingJackson2HttpMessageConverter(json)).build();
        Map<String,Object> cases=new TreeMap<>();
        cases.put("health",http(mvc,get("/web/health")));
        cases.put("data-all-models",http(mvc,get("/data/allModels")));
        cases.put("data-preview-missing-param",http(mvc,get("/data/previewData")));
        cases.put("query-sse",http(mvc,post("/web/api/v1/gpt/queryAgentStreamIncr").contentType(MediaType.APPLICATION_JSON).content("{\"query\":\"中文\",\"sessionId\":\"session-p0\",\"requestId\":\"req-p0\"}")));
        cases.put("query-malformed",http(mvc,post("/web/api/v1/gpt/queryAgentStreamIncr").contentType(MediaType.APPLICATION_JSON).content("{")));
        cases.put("query-empty-body",http(mvc,post("/web/api/v1/gpt/queryAgentStreamIncr").contentType(MediaType.APPLICATION_JSON)));
        cases.put("stop-empty-id",http(mvc,post("/api/agent/run/stop").contentType(MediaType.APPLICATION_JSON).content("{}")));
        cases.put("inject-empty-id",http(mvc,post("/api/agent/run/inject").contentType(MediaType.APPLICATION_JSON).content("{}")));
        cases.put("inject-empty-text",http(mvc,post("/api/agent/run/inject").contentType(MediaType.APPLICATION_JSON).content("{\"requestId\":\"req-p0\"}")));
        cases.put("follow-empty-id",http(mvc,post("/api/agent/run/follow").contentType(MediaType.APPLICATION_JSON).content("{}")));
        cases.put("genui-invalid",http(mvc,post("/api/agent/genui/export/pdf").contentType(MediaType.APPLICATION_JSON).content("{}")));
        cases.put("unknown-route",http(mvc,get("/not-a-real-route")));
        behavior.put("http",cases);
        String stream=(String)((Map<?,?>)cases.get("query-sse")).get("body");
        assertTrue(stream.startsWith("data:"));assertFalse(stream.contains("event:"));assertFalse(stream.contains("id:"));assertFalse(stream.contains("[DONE]"));
    }
    static void captureSerialization() throws Exception {
        Map<String,Object> samples=new TreeMap<>();
        samples.put("gpt-default",new GptProcessResult());samples.put("gpt-builder",GptProcessResult.builder().build());
        samples.put("heartbeat",AgentResponseProjectionStream.buildHeartbeat("req-p0"));
        samples.put("follow-pending",AgentResponseProjectionStream.buildFollowPending("req-p0",800L));
        samples.put("tool-text",ToolResultPayload.text("中文\nresult"));samples.put("tool-data",ToolResultPayload.okData("test_tool",Map.of("runId",9007199254740993L,"decimal",new java.math.BigDecimal("1.2300"))));
        samples.put("tool-error",ToolResultPayload.failureFrom("timeout",null));
        samples.put("local-time",LocalDateTime.of(2026,10,2,22,0,0));
        Map<String,Object> tree=Map.of("nodeId","n-p0","kind","Stat","props",Map.of("label","中文 baseline","value","42"));
        EmitUiTreeTool tool=new EmitUiTreeTool();Object emitted=tool.execute(Map.of("tree",tree,"canvas_id","canvas-p0"));
        assertFalse(((ToolResultPayload)emitted).getFailed());samples.put("genui-tree",emitted);
        samples.put("genui-patch",GenUiSchema.validateUiPatch(Map.of("canvas_id","canvas-p0","seq",1,"patches",List.of(Map.of("op","replace","path","/root/props/content","value","updated")))));
        samples.put("genui-invalid",tool.execute(Map.of("tree",Map.of("type","UnsafeComponent"))));
        ReactorConfig cfg=new ReactorConfig();ReflectionTestUtils.setField(cfg,"reactorBasePrompt","p0-base-prompt");GptQueryAgentRequestFactory factory=new GptQueryAgentRequestFactory(cfg);
        VisitorRequestContext.bind("visitor-p0");
        try {
            for(int deep:List.of(0,1,-1)) {GptQueryReq req=GptQueryReq.builder().query("中文").sessionId("session-p0").requestId(" req-p0 ").deepThink(deep).build(); factory.normalize(req);samples.put("normalized-"+deep,req);samples.put("request-"+deep,factory.build(req));}
            GptQueryReq defaults=GptQueryReq.builder().requestId("req-p0").sessionId("session-p0").build();factory.normalize(defaults);samples.put("normalized-defaults",defaults);
        }finally{VisitorRequestContext.clear();}
        behavior.put("serialization",samples);
    }
    static void captureHitl() throws Exception {
        IUserQuestionRepository repo=Mockito.mock(IUserQuestionRepository.class);
        UserQuestionRecord record=UserQuestionRecord.builder().questionId("q-p0").visitorId("visitor-owner").sessionId("session-p0")
            .status(UserQuestionStatuses.RESUME_PENDING).resumeRequestId("resume-p0").expiresAt(LocalDateTime.of(2000,1,1,0,0)).build();
        Mockito.when(repo.findByQuestionId("q-p0")).thenAnswer(c->Optional.of(record));
        AskUserQuestionApplicationService service=new AskUserQuestionApplicationService(repo);Map<String,Object> cases=new TreeMap<>();
        VisitorRequestContext.bind("visitor-other");cases.put("foreign-answer",service.answer("q-p0",Map.of()));
        VisitorRequestContext.clear();cases.put("missing-identity-answer",service.answer("q-p0",Map.of()));
        VisitorRequestContext.bind("visitor-owner");cases.put("duplicate-answer",service.answer("q-p0",Map.of()));
        record.setStatus(UserQuestionStatuses.PENDING);
        Mockito.when(repo.casAnswerPending(Mockito.anyString(),Mockito.anyString(),Mockito.anyMap(),Mockito.anyString())).thenAnswer(c->{record.setStatus(UserQuestionStatuses.RESUME_PENDING);record.setResumeRequestId(c.getArgument(3));return true;});
        Map<String,Object> expired=service.answer("q-p0",Map.of("choice","yes"));
        assertEquals(true,expired.get("accepted"));assertTrue(((String)expired.get("resumeRequestId")).startsWith("resume_"));
        Map<String,Object> expiredRepeat=service.answer("q-p0",Map.of("choice","yes"));
        assertEquals(expired.get("resumeRequestId"),expiredRepeat.get("resumeRequestId"));assertEquals(true,expiredRepeat.get("idempotent"));
        cases.put("expired-answer-accepted",expired);cases.put("expired-answer-repeat",expiredRepeat);VisitorRequestContext.clear();
        ToolCall call=ToolCall.builder().id("call-p0").type("function").function(ToolCall.Function.builder().name("ExitPlanMode").arguments("{}").build()).build();
        PlanApprovalRecord approval=PlanApprovalRecord.builder().approvalId("pa-p0").toolCallId("call-p0").planContent("## plan").decision(PlanApprovalDecision.builder().approved(true).build()).build();
        cases.put("approval-observation",PlanApprovalResumeApplicationService.appendDecisionObservation(List.of(Message.fromToolCalls("plan",List.of(call)),Message.toolMessage("waiting","call-p0",null)),approval));
        org.wwz.ai.domain.agent.runtime.cancel.ActiveAgentRunRegistry registry=new org.wwz.ai.domain.agent.runtime.cancel.ActiveAgentRunRegistry();
        registry.begin("req-foreign","session-owner","visitor-owner");VisitorRequestContext.bind("visitor-other");
        Map<String,Object> stopped=new org.wwz.ai.application.agent.run.AgentRunStopApplicationService(registry).stop(null,"req-foreign");
        assertEquals(true,stopped.get("stopped"));cases.put("foreign-stop-accepted",stopped);VisitorRequestContext.clear();
        behavior.put("hitl",cases);
    }
    static void captureH2() throws Exception {
        H2DialectFactory factory=new H2DialectFactory();Map<String,Object> result=new TreeMap<>();
        result.put("accepts-memory",factory.acceptsURL("jdbc:h2:mem:p0"));result.put("accepts-file",factory.acceptsURL("jdbc:h2:file:/isolated/p0"));
        result.put("accepts-tcp",factory.acceptsURL("jdbc:h2:tcp://127.0.0.1/p0"));
        result.put("spi-driver",JdbcDialectLoader.load("jdbc:h2:mem:p0").driverName());
        JdbcConnectionConfig config=new JdbcConnectionConfig();config.setKey("p0");config.setUrl("jdbc:h2:mem:p0;MODE=MySQL;DB_CLOSE_DELAY=-1"); config.setUserName("sa");config.setPassword("");
        DatasourceWrapper datasource=new JdbcConnectionPoolFactory().createPooledDatasource(config);
        try(Connection c=datasource.getDataSource().getConnection();Statement stmt=c.createStatement()) {
            stmt.execute("create table p0_sample(id bigint primary key, amount decimal(18,4), title varchar(80))");
            stmt.execute("insert into p0_sample values(9007199254740993,1.2300,'中文')");
            try(ResultSet r=stmt.executeQuery("select id,amount,title from p0_sample")) {assertTrue(r.next());result.put("row",Map.of("id",r.getLong(1),"amount",r.getBigDecimal(2).toPlainString(),"title",r.getString(3)));}
            result.put("catalog",datasource.getCatalog().getClass().getName());
        }finally{((com.zaxxer.hikari.HikariDataSource)datasource.getDataSource()).close();}
        org.wwz.ai.domain.agent.reactor.config.data.DbConfig db=new org.wwz.ai.domain.agent.reactor.config.data.DbConfig();
        db.setKey("p0-adapter");db.setType("h2");db.setUrl(config.getUrl());db.setUsername("sa");db.setPassword("");
        var queried=new org.wwz.ai.infrastructure.dataquery.DataQueryExecutionAdapter(new org.wwz.ai.infrastructure.dataquery.provider.jdbc.JdbcDataProvider()).query(db,"select id,amount,title from p0_sample",1);
        result.put("adapter",Map.of("columns",queried.getColumnList(),"rows",queried.getDataList(),"size",queried.getDataSize(),"sql",queried.getQuerySql()));
        var connection=JdbcConnectionFactory.getConnection(org.wwz.ai.infrastructure.dataquery.util.JdbcUtils.parseJdbcConnectionConfig(db));
        ((com.zaxxer.hikari.HikariDataSource)connection.getDatasourceWrapper().getDataSource()).close();
        assertEquals(false,result.get("accepts-file"));behavior.put("h2",result);
    }
    static Object field(Object obj,String name)throws Exception {Field f=obj.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(obj);}
    static void captureHistory()throws Exception {
        Class<?> type=Class.forName("org.wwz.ai.test.domain.ExecutionLedgerFixtureFactory");
        Method make=type.getDeclaredMethod("newLedgerTestContext");make.setAccessible(true);Object ctx=make.invoke(null);
        Object helper=Class.forName("org.wwz.ai.test.domain.ConversationHistoryControllerTest").getConstructor().newInstance();
        Method seed=Arrays.stream(helper.getClass().getDeclaredMethods()).filter(m->m.getName().equals("seedRun")&&m.getParameterCount()==9).findFirst().orElseThrow();seed.setAccessible(true);
        seed.invoke(helper,ctx,"req-history-p0","session-history-p0","file_tool","中文历史",LocalDateTime.of(2026,10,2,22,0),1,"history summary","report-p0.md");
        org.wwz.ai.trigger.http.agent.AgentConversationHistoryController controller=new org.wwz.ai.trigger.http.agent.AgentConversationHistoryController();
        ReflectionTestUtils.setField(controller,"executionLedgerQueryService",field(ctx,"queryService"));
        ReflectionTestUtils.setField(controller,"conversationHistoryReplayService",field(ctx,"replayService"));
        ReflectionTestUtils.setField(controller,"conversationSessionOwnershipApplicationService",Mockito.mock(org.wwz.ai.application.agent.visitor.ConversationSessionOwnershipApplicationService.class));
        MockMvc mvc=MockMvcBuilders.standaloneSetup(controller)
            .setMessageConverters(new org.springframework.http.converter.json.MappingJackson2HttpMessageConverter(json)).build();
        VisitorRequestContext.bind("visitor-test");
        try {behavior.put("history",Map.of("detail",http(mvc,get("/api/agent/conversation/sessions/session-history-p0")),"list",http(mvc,get("/api/agent/conversation/sessions"))));}
        finally{VisitorRequestContext.clear();}
    }
    static void captureSql()throws Exception {
        org.apache.ibatis.datasource.unpooled.UnpooledDataSource ds=new org.apache.ibatis.datasource.unpooled.UnpooledDataSource("org.h2.Driver","jdbc:h2:mem:p0cas;MODE=MySQL;DB_CLOSE_DELAY=-1","sa","");
        try(Connection c=ds.getConnection();Statement stmt=c.createStatement()) {
            stmt.execute("create table ai_agent_user_question(question_id varchar(80),visitor_id varchar(80),status varchar(80),resume_request_id varchar(80),answers_json clob,expires_at timestamp,update_time timestamp,deleted int)");
            stmt.execute("insert into ai_agent_user_question values('q-cas','visitor-owner','PENDING',null,null,TIMESTAMP '2000-01-01 00:00:00',CURRENT_TIMESTAMP,0)");
        }
        org.apache.ibatis.session.Configuration cfg=new org.apache.ibatis.session.Configuration(new org.apache.ibatis.mapping.Environment("p0",new org.apache.ibatis.transaction.jdbc.JdbcTransactionFactory(),ds));
        Path xml=root.resolve("Reactor-agent-app/src/main/resources/mybatis/mapper/user_question_mapper.xml");
        try(var in=Files.newInputStream(xml)){new org.apache.ibatis.builder.xml.XMLMapperBuilder(in,cfg,xml.toString(),cfg.getSqlFragments()).parse();}
        String ns="org.wwz.ai.infrastructure.dao.reactor.IUserQuestionDao.";Map<String,Object> results=new TreeMap<>();
        try(var session=new org.apache.ibatis.session.SqlSessionFactoryBuilder().build(cfg).openSession(true)) {
            Map<String,Object> params=new HashMap<>(Map.of("questionId","q-cas","visitorId","visitor-other","answersJson","{}","resumeRequestId","resume-cas"));
            assertEquals(0,session.update(ns+"casAnswerPending",params));results.put("foreign-answer-rows",0);
            params.put("visitorId","visitor-owner");int answer=session.update(ns+"casAnswerPending",params);assertEquals(1,answer);results.put("expired-answer-rows",answer);
            int claim=session.update(ns+"casClaimResume",params);assertEquals(1,claim);results.put("first-claim-rows",claim);
            int duplicate=session.update(ns+"casClaimResume",params);assertEquals(0,duplicate);results.put("duplicate-claim-rows",duplicate);
            params.put("fromStatuses",List.of("PENDING","RESUME_PENDING"));int cancel=session.update(ns+"casCancel",params);assertEquals(0,cancel);results.put("cancel-resuming-rows",cancel);
            int finish=session.update(ns+"markAnswered",params);assertEquals(1,finish);results.put("mark-answered-rows",finish);
            params.put("status","FAILED");int late=session.update(ns+"markFailed",params);assertEquals(1,late);results.put("late-failure-overwrites-answered-rows",late);
            try(var stmt=session.getConnection().createStatement();var rows=stmt.executeQuery("select status from ai_agent_user_question")){rows.next();assertEquals("FAILED",rows.getString(1));results.put("final-status",rows.getString(1));}
        }
        behavior.put("actual-mapper-h2-cas",results);
    }

}
