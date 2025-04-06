# FastAPI entry point; includes API orchestration and async event loop
# app/main.py
from fastapi import FastAPI
from app.endpoints import questions, hints, feedback

app = FastAPI(title="AI Tutor POC")

app.include_router(questions.router, prefix="/questions", tags=["Questions"])
app.include_router(hints.router, prefix="/hints", tags=["Hints"])
app.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])

@app.get("/")
async def root():
    return {"message": "Welcome to the AI Tutor API. Visit /questions, /hints, or /feedback for more information."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
