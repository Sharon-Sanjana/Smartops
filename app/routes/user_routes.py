
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.dependencies import get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserLogin,
)
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    verify_token,
    get_current_user,
    require_admin,
)

router = APIRouter()


@router.post("/users", response_model=UserResponse)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
):
    existing_user = (
        db.query(User)
        .filter(User.email == user.email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered",
        )

    new_user = User(
        name=user.name,
        email=user.email,
        password=hash_password(user.password),
        role="engineer",
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


@router.get("/users", response_model=list[UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    return db.query(User).all()


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.lower() != "admin" and current_user.id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only access your own profile",
        )

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return user


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    existing_email = (
        db.query(User)
        .filter(
            User.email == user_data.email,
            User.id != user_id,
        )
        .first()
    )

    if existing_email:
        raise HTTPException(
            status_code=400,
            detail="Email already registered",
        )

    user.name = user_data.name
    user.email = user_data.email
    user.role = user_data.role

    db.commit()
    db.refresh(user)

    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="Admins cannot delete their own account",
        )

    db.delete(user)
    db.commit()

    return {"message": "User deleted successfully"}


@router.post("/login")
def login(
    user_data: UserLogin,
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == user_data.email)
        .first()
    )

    if not user or not verify_password(
        user_data.password,
        user.password,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    access_token = create_access_token(
        data={"sub": str(user.id)}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }
