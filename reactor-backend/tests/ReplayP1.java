import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.wwz.ai.domain.agent.ledger.model.*;
import org.wwz.ai.domain.agent.ledger.model.replay.ReplayFactBundle;
import org.wwz.ai.domain.agent.ledger.replay.ReplayProjector;
import org.wwz.ai.domain.agent.ledger.replay.projector.ToolInvocationProjectorRegistry;
import org.wwz.ai.domain.agent.ledger.replay.projector.impl.*;
import org.wwz.ai.domain.agent.ledger.model.tooloutput.*;
import java.nio.file.*;
import java.util.*;

/** Read-only original Java projector over actual isolated Python-written SQL rows. */
public class ReplayP1 {
    static ObjectMapper json=new ObjectMapper().registerModule(new JavaTimeModule())
        .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES,false)
        .configure(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS,false);
    static ObjectNode map(JsonNode source) {
        ObjectNode target=json.createObjectNode();
        source.fields().forEachRemaining(e -> {
            StringBuilder name=new StringBuilder(); boolean upper=false;
            for(char c:e.getKey().toCharArray()) {
                if(c=='_') upper=true;
                else {name.append(upper?Character.toUpperCase(c):c);upper=false;}
            }
            String key=e.getKey().equals("llm_oberserve")?"llmObservation":name.toString();
            JsonNode value=e.getValue();
            if(value.isTextual() && (key.endsWith("At") || key.endsWith("Time")))
                value=new TextNode(value.asText().replace(' ','T'));
            target.set(key,value);
        });
        return target;
    }
    static <T> List<T> list(JsonNode source,Class<T> type,String requestId) throws Exception {
        List<T> values=new ArrayList<>();
        for(JsonNode row:source) {
            ObjectNode mapped=map(row);
            if(type==ToolInvocationView.class) mapped.put("requestId",requestId);
            mapped.remove("structuredOutput");
            T instance=json.treeToValue(mapped,type);
            if(instance instanceof ToolInvocationView tool && row.hasNonNull("structured_output")) {
                JsonNode output=row.get("structured_output");
                if(tool.getToolName().equals("emit_ui_tree")) {
                    GenUiTreeToolOutput value=new GenUiTreeToolOutput();
                    value.setCanvasId(output.path("canvas_id").asText(null));
                    if(output.hasNonNull("tree_json")) value.setTree(json.readValue(output.get("tree_json").asText(),Map.class));
                    tool.setStructuredOutput(value);
                } else if(tool.getToolName().equals("emit_ui_patch")) {
                    GenUiPatchToolOutput value=new GenUiPatchToolOutput();
                    value.setCanvasId(output.path("canvas_id").asText(null));
                    if(output.hasNonNull("seq")) value.setSeq(output.get("seq").asInt());
                    if(output.hasNonNull("patches_json")) value.setPatches(json.readValue(output.get("patches_json").asText(),List.class));
                    tool.setStructuredOutput(value);
                } else {
                    Class<? extends ToolStructuredOutput> cls=switch(tool.getToolName()) {
                        case "code_interpreter" -> CodeInterpreterToolOutput.class;
                        case "data_analysis" -> DataAnalysisToolOutput.class;
                        case "multimodalagent_tool" -> MultimodalAgentToolOutput.class;
                        case "image_generation_tool" -> ImageGenerationToolOutput.class;
                        case "canvas_publish" -> CanvasPublishToolOutput.class;
                        case "deep_search" -> DeepSearchToolOutput.class;
                        default -> null;
                    };
                    if(cls!=null) {
                        ObjectNode typed=map(output);
                        if(cls==DeepSearchToolOutput.class) {
                            JsonNode stages=json.readTree(output.path("stages_json").asText("[]"));
                            typed.set("stages",stages);
                            ArrayNode chapters=json.createArrayNode();
                            for(JsonNode stage:stages) if(stage.path("stage").asText().equals("chapter_summary")) {
                                ObjectNode chapter=json.createObjectNode();
                                chapter.set("chapterId",stage.get("chapterId"));chapter.set("title",stage.get("chapterTitle"));
                                chapter.set("content",stage.get("chapterContent"));chapter.set("order",stage.get("chapterOrder"));
                                chapter.set("queries",stage.get("queries"));chapters.add(chapter);
                            }
                            typed.set("chapters",chapters);
                        }
                        tool.setStructuredOutput(json.treeToValue(typed,cls));
                    }
                }
            }
            values.add(instance);
        }
        return values;
    }
    public static void main(String[] args) throws Exception {
        JsonNode facts=json.readTree(Path.of(args[0]).toFile());
        DialogueRunView run=json.treeToValue(map(facts.get("run")),DialogueRunView.class);
        ReplayFactBundle bundle=ReplayFactBundle.builder().run(run)
            .llmInvocations(list(facts.get("llms"),LlmInvocationView.class,run.getRequestId()))
            .toolInvocations(list(facts.get("tools"),ToolInvocationView.class,run.getRequestId()))
            .artifacts(list(facts.get("artifacts"),ArtifactView.class,run.getRequestId())).build();
        ReplayProjector projector=new ReplayProjector(new ToolInvocationProjectorRegistry(List.of(new GenUiTreeToolInvocationProjector(),new GenUiPatchToolInvocationProjector(),new CodeInterpreterToolInvocationProjector(),new DataAnalysisToolInvocationProjector(),new MultiModalToolInvocationProjector(),new ImageGenerationToolInvocationProjector(),new CanvasPublishToolInvocationProjector(),new DeepSearchToolInvocationProjector(),new AskUserQuestionToolInvocationProjector()),new DefaultToolInvocationProjector()));
        json.writerWithDefaultPrettyPrinter().writeValue(Path.of(args[1]).toFile(),projector.projectHistoryFrames(bundle));
    }
}
