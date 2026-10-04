import com.alibaba.fastjson.JSON;
import org.wwz.ai.domain.agent.memory.*;
import org.wwz.ai.domain.agent.runtime.dto.Message;
import org.wwz.ai.domain.agent.runtime.dto.tool.ToolCall;
import org.junit.runner.JUnitCore;
import java.nio.file.*;
import java.util.*;

/** Offline original working-memory producer; never starts Spring or reads profiles. */
public class MemoryP4 {
    public static void main(String[] args) throws Exception {
        var call=ToolCall.builder().id("old-call").type("function").function(ToolCall.Function.builder().name("old.name").arguments("{\"amount\":125}").build()).build();
        List<Message> messages=List.of(Message.userMessage("旧轮证据 Unicode 金额125",null),Message.fromToolCalls(null,"old model reasoning",List.of(call)),Message.toolMessage("旧工具成功：125","old-call",null));
        var projector=new WorkingMemoryProjector();
        var projected=projector.project(messages,"p4-old-session","main","p4-java-old-projection",null);
        Files.writeString(Path.of(args[0]),JSON.toJSONString(projected));
        int count=0;
        for(int i=1;i<args.length;i++) {
            var result=new JUnitCore().run(Class.forName(args[i])); count+=result.getRunCount();
            if(!result.wasSuccessful())throw new AssertionError(result.getFailures());
        }
        System.out.println("Original Java working-memory projection emitted; isolated JUnit passed: "+count);
    }
}
