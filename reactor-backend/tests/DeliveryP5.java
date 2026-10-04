import com.alibaba.fastjson.JSON;
import java.nio.file.*;
import java.util.*;
import org.wwz.ai.domain.agent.runtime.tool.BaseTool;
import org.wwz.ai.domain.agent.runtime.tool.common.canvas.*;

/** Pure original Java payload capture. No Spring, profiles, accounts or external calls. */
public class DeliveryP5 {
 public static void main(String[] args) throws Exception {
  Path output=Path.of(args[0]);Files.createDirectories(output);
  Map<String,Object> schema=new LinkedHashMap<>();
  for(BaseTool tool:List.of(new org.wwz.ai.domain.agent.runtime.tool.common.ImageGenerationTool(),new EmitUiTreeTool(),new EmitUiPatchTool(),new CanvasPublishTool(),new GetGenuiGuideTool(),new GetHtmlCanvasGuideTool(),new ListUiComponentsTool())) {
   schema.put(tool.getName(),Map.of("type","function","function",Map.of("name",tool.getName(),"description",tool.getDescription(),"parameters",tool.toParams())));
  }
  Files.writeString(output.resolve("p5_schemas.json"),JSON.toJSONString(schema));
  Files.writeString(output.resolve("genui_payloads.json"),JSON.toJSONString(Map.of("get_genui_guide",GenUiGuidePayload.payload(),"get_html_canvas_guide",HtmlCanvasGuidePayload.payload(),"components",GenUiCatalog.listCatalog())));
 }
}
