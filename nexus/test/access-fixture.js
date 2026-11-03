// Synthetic RSA keys only. The real verifier still checks signatures and every
// Access claim; tests replace only the team's public certificate endpoint.
export async function testAccess() {
  const keys=await crypto.subtle.generateKey({name:"RSASSA-PKCS1-v1_5",modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:"SHA-256"},true,["sign","verify"]);
  const jwk={...await crypto.subtle.exportKey("jwk",keys.publicKey),kid:"synthetic-test-key",alg:"RS256",use:"sig"};
  const origin="https://nexus-test.cloudflareaccess.com";
  const encode=(value)=>Buffer.from(JSON.stringify(value)).toString("base64url");
  async function sign(identity) {
    const content=encode({alg:"RS256",kid:jwk.kid})+"."+encode({iss:origin,aud:["test-aud"],exp:Math.floor(Date.now()/1000)+3600,...identity});
    const signature=await crypto.subtle.sign("RSASSA-PKCS1-v1_5",keys.privateKey,new TextEncoder().encode(content));
    return content+"."+Buffer.from(signature).toString("base64url");
  }
  const tokens={user:await sign({sub:"synthetic-person"}),agent:await sign({sub:"",common_name:"synthetic-client"}),neither:await sign({})};
  globalThis.fetch=async(url)=>{
    if(String(url)!==origin+"/cdn-cgi/access/certs")throw new Error("a test attempted an unexpected network request");
    return new Response(JSON.stringify({keys:[jwk]}),{headers:{"Content-Type":"application/json"}});
  };
  return {env:{ACCESS_AUD:"test-aud",ACCESS_TEAM_DOMAIN:"nexus-test.cloudflareaccess.com"},ctx:{access:{aud:"test-aud"}},
    headers:(kind="user")=>({"Cf-Access-Jwt-Assertion":tokens[kind]})};
}
