import streamlit as st

def main():
    st.title("Secrets Test App")
    
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
        st.success(f"Successfully loaded OpenAI API key: {api_key[:5]}...")
    except Exception as e:
        st.error(f"Failed to load secret: {str(e)}")

if __name__ == "__main__":
    main()
