from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from core.database import get_db
from core.deps import get_current_user
from models import User
from models.enums import MemoryKind
from schemas.memory import MemoryCreate, MemoryResponse, MemoryUpdate
from services.memories import (
    create_memory,
    delete_memory,
    list_memories,
    update_memory,
)


router = APIRouter(prefix="/api/agent/memories", tags=["Agent 记忆"])


@router.get("", response_model=list[MemoryResponse])
def read_memories(
    topic_id: int | None = Query(default=None, ge=1),
    kind: MemoryKind | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_memories(db, user_id=current_user.id, topic_id=topic_id, kind=kind)


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def add_memory(
    request: MemoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return create_memory(
        db,
        user_id=current_user.id,
        kind=request.kind,
        content=request.content,
        topic_id=request.topic_id,
    )


@router.patch("/{memory_id}", response_model=MemoryResponse)
def edit_memory(
    memory_id: int,
    request: MemoryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return update_memory(
        db,
        user_id=current_user.id,
        memory_id=memory_id,
        updates=request.model_dump(exclude_unset=True),
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_memory(
    memory_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    delete_memory(db, user_id=current_user.id, memory_id=memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
