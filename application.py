import os
import streamlit as st
import requests
from langchain_google_vertexai import ChatVertexAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
import vertexai
from langchain_community.utilities.sql_database import SQLDatabase
from langchain.agents import create_sql_agent
from langchain.agents.agent_types import AgentType



# --- Gemini LangChain Setup ---
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/Users/evanwoo/Desktop/CRISPR_copilot/weighty-country-457719-j1-c0ab901048f4.json"
vertexai.init(project="weighty-country-457719-j1", location="us-central1")

v_llm = ChatVertexAI(
    model_name="gemini-2.0-flash-lite-001",
    temperature=0.3,
    max_tokens=1500
)

prompt = ChatPromptTemplate.from_messages([
    ("system", "{system_message}"),
    MessagesPlaceholder("messages")
])

ready_llm = prompt | v_llm

# --- LangChain SQL DB Wrapper ---
sql_db = SQLDatabase.from_uri(f"postgresql://postgres:{st.secrets['DB_PASSWORD']}@localhost:5432/mEdit")

sql_agent = create_sql_agent(
    llm=v_llm,
    db=sql_db,
    agent_type=AgentType.OPENAI_FUNCTIONS,  # works with Gemini via LangChain
    verbose=True,
)

# --- API Fallback Functions ---
def fetch_histology(mondo_id):
    url = f"https://api.monarchinitiative.org/v3/api/histopheno/{mondo_id}?format=json"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        return [item.get("label", "") for item in data.get("items", []) if "label" in item]
    except Exception:
        return []

def fetch_mondo_rsid(rsid):
    # Placeholder for extracting MONDO ID from RSID using a real API
    # In reality you'd need to use an ID resolver or intermediate mapping
    return "MONDO:0013342" if rsid else None

def fetch_prevalence(orphanet_code):
    # Example fallback function
    url = f"https://www.orphadata.com/api/prevalence/{orphanet_code}"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return res.json().get("prevalence")
    except Exception:
        return None


# --- Streamlit UI ---
st.title("CRISPR Copilot: Smart Companion to mEdit")

st.markdown("""
This tool assists clinicians and researchers in navigating disease-causing mutations. 
Enter a variant or upload a screenshot, and we'll help with interpretation, histology, or even generate CRISPR guides.
""")

query = st.text_input("Enter a genomic coordinate or HGVS (HG38) mutation (e.g. chr1:123456A>T, NM_017547.4...), or just a general question:")
img_file = st.file_uploader("Or upload a screenshot with mutation details:", type=["png", "jpg", "jpeg"])

# --- Main Logic ---
if st.button("Analyze Input"):
    with st.spinner("Processing your input..."):
        variant_input = query

        if img_file:
            st.markdown("image and file extraction coming soon..")

        # Use Gemini with LangChain pipeline
        mEdit_readme = "mEdit is a Python-based CRISPR guide RNA design tool that takes genomic coordinates or HGVS variants as input and generates candidate guides using the GRCh38 reference genome; it supports various endonucleases and base editors, can predict off-target effects, optionally uses alternative genomes or custom VCFs, and is installed via pip with commands like db_set for database setup and guide_prediction for generating editing guides."
        response = ready_llm.invoke({
            "system_message": f"You are a genomics assistant helping interpret user input. the following is the mEdit readme: {mEdit_readme}",
            "messages": [("human", f"This user input represents: '{variant_input}'. Is this a valid genomic coordinate or HGVS mutation suitable for mEdit analysis, specifically in strict HG38 format? Respond yes or no and explain.")]
        })

        kind = response.content.strip().lower()

        if "yes" in kind:
            st.success("Input looks suitable for mEdit analysis.")

            try:
                sql_response = sql_agent.run(f"{variant_input}")
                st.subheader("AI-Generated Response from VariantMetadata DB")
                st.markdown(sql_response)

                # Dynamic fallback enrichment using API if fields are missing
                if "None" in sql_response or "null" in sql_response:
                    rsid_match = next((word for word in sql_response.split() if word.startswith("rs")), None)
                    if rsid_match:
                        mondo_id = fetch_mondo_rsid(rsid_match)
                        if mondo_id:
                            histo = fetch_histology(mondo_id)
                            if histo:
                                st.markdown(f"**Additional Histology Info (from MONDO API):** {', '.join(histo)}")

            except Exception as e:
                st.error(f"Failed to process database query: {e}")


        else:
            st.info("Input may not be suitable for genomic coordinate processing. Responding as a general assistant...")
            generic_resp = ready_llm.invoke({
                "system_message": "You are a smart CRISPR assistant.",
                "messages": [("human", f"Help with: {variant_input}")]
            })
            st.markdown(generic_resp.content.strip())

            try:
                sql_response = sql_agent.run(f"{variant_input}")
                st.subheader("AI-Generated Response from VariantMetadata DB")
                st.markdown(sql_response)
            except Exception as e:
                st.error(f"Failed to process database query: {e}")

# Close DB
# cur.close()
# conn.close()