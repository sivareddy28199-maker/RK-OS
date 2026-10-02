// =========================================================
// RK OS — Frontend Controller
// =========================================================

document.addEventListener("DOMContentLoaded", async () => {
    initializeNavigation();
    initializeDate();
    rkStudyRestoreTimerState();
    rkStudySyncTimerDisplay();
    checkBackendStatus();
    await rkCreateDashboardSnapshot();
    await rkRefreshRKOSData({ tasks: true, habits: true, goals: true, study: true });
    await Promise.all([rkLoadProfile(), rkLoadAssistantHistory()]);
});


// =========================================================
// NAVIGATION
// =========================================================

function initializeNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const sections = document.querySelectorAll(".page-section");
    const pageTitle = document.getElementById("page-title");

    navItems.forEach((item) => {

        item.addEventListener("click", () => {

            const targetSection = item.dataset.section;

            // Remove active state
            navItems.forEach((nav) => {
                nav.classList.remove("active");
            });

            sections.forEach((section) => {
                section.classList.remove("active-section");
            });

            // Activate selected item
            item.classList.add("active");

            const target = document.getElementById(targetSection);

            if (target) {
                target.classList.add("active-section");
            }

            // Update page title
            const title = item.textContent.trim();

            if (pageTitle) {
                pageTitle.textContent = title;
            }

            if (targetSection === "dashboard") {
                loadDashboardData();
                rkCreateDashboardSnapshot();
            } else if (targetSection === "assistant") {
                rkLoadAssistantHistory();
            } else if (targetSection === "routines") {
                rkLoadTasks();
                rkLoadHabits();
                rkLoadGoals();
                rkLoadRoutinesSummary();
            } else if (targetSection === "tasks") {
                rkLoadTasks();
            } else if (targetSection === "habits") {
                rkLoadHabits();
            } else if (targetSection === "goals") {
                rkLoadGoals();
            } else if (targetSection === "learn") {
                rkLoadStudyPage();
            } else if (targetSection === "profile") {
                rkLoadProfile();
            } else if (targetSection === "progress") {
                rkRefreshRKOSData();
            }
        });

    });
}

function rkNavigateToSection(section) {
    const item = document.querySelector(`.nav-item[data-section="${section}"]`);
    if (item) item.click();
}


// =========================================================
// DATE
// =========================================================

function initializeDate() {

    const dayElement = document.getElementById("current-day");
    const dateElement = document.getElementById("current-date");

    const now = new Date();

    const day = now.toLocaleDateString("en-IN", {
        weekday: "long"
    });

    const date = now.toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric"
    });

    if (dayElement) {
        dayElement.textContent = day;
    }

    if (dateElement) {
        dateElement.textContent = date;
    }
}


// =========================================================
// BACKEND STATUS
// =========================================================

async function checkBackendStatus() {

    const statusElement =
        document.getElementById("backend-status");

    try {

        const response =
            await fetch("/api/status");

        if (!response.ok) {
            throw new Error("Backend request failed");
        }

        const data =
            await response.json();

        if (statusElement) {

            statusElement.textContent =
                `${data.app} Online`;

        }

        console.log("RK OS backend:", data);

    } catch (error) {

        console.error(
            "Unable to connect to RK OS backend:",
            error
        );

        if (statusElement) {

            statusElement.textContent =
                "Backend Offline";

        }

    }
}


// =========================================================
// DASHBOARD DATA
// =========================================================

async function loadDashboardData() {

    try {

        const [response, routinesResponse] = await Promise.all([
            fetch("/api/dashboard"),
            fetch("/api/routines/summary")
        ]);

        if (!response.ok || !routinesResponse.ok) {
            throw new Error("Dashboard API request failed");
        }

        const [data, routines] = await Promise.all([response.json(), routinesResponse.json()]);

        const tasksElement =
            document.getElementById("task-count");

        const habitsElement =
            document.getElementById("habit-count");

        const goalsElement =
            document.getElementById("goal-count");

        if (tasksElement) {
            tasksElement.textContent = data.tasks;
        }

        if (habitsElement) {
            habitsElement.textContent = data.habits;
        }

        if (goalsElement) {
            goalsElement.textContent = data.goals;
        }

        rkRenderRoutineSummary(routines);

        const studyElement = document.getElementById("dashboard-study-time");
        const studySessionsElement = document.getElementById("dashboard-study-sessions");
        const studyTopicsElement = document.getElementById("dashboard-study-topics");
        const practiceQuestionsElement = document.getElementById("dashboard-practice-questions");
        const practiceAccuracyElement = document.getElementById("dashboard-practice-accuracy");
        const quizAccuracyElement = document.getElementById("dashboard-quiz-accuracy");

        if (data.study) {
            if (studyElement) studyElement.textContent = `${Math.max(0, Number(data.study.study_minutes || 0))}m`;
            if (studySessionsElement) studySessionsElement.textContent = Number(data.study.sessions || 0);
            if (studyTopicsElement) studyTopicsElement.textContent = Number(data.study.topics_studied || 0);
        } else {
            if (studyElement) studyElement.textContent = "0m";
            if (studySessionsElement) studySessionsElement.textContent = "0";
            if (studyTopicsElement) studyTopicsElement.textContent = "0";
        }

        const practice = data.practice || {};
        if (practiceQuestionsElement) practiceQuestionsElement.textContent = Number(practice.today_questions || 0);
        if (practiceAccuracyElement) practiceAccuracyElement.textContent = `${Number(practice.today_accuracy || 0)}%`;
        if (quizAccuracyElement) quizAccuracyElement.textContent = `${Number((data.quiz || {}).accuracy || 0)}%`;

        const habitTotal = Number((routines.habits || {}).total || 0);
        const habitComplete = Number((routines.habits || {}).completed_today || 0);
        const routineCompletion = document.getElementById("dashboard-routine-completion");
        const focusSessions = document.getElementById("dashboard-study-sessions-card");
        const questionTotal = document.getElementById("dashboard-question-total");
        const overallAccuracy = document.getElementById("dashboard-overall-accuracy");
        const questionsToday = Number(practice.today_questions || 0) + Number(((data.quiz || {}).today || {}).questions || 0);
        const correctToday = Number(practice.today_correct || 0) + Number(((data.quiz || {}).today || {}).correct || 0);
        if (routineCompletion) routineCompletion.textContent = `${habitComplete}/${habitTotal}`;
        if (focusSessions) focusSessions.textContent = Number((data.study || {}).sessions || 0);
        if (questionTotal) questionTotal.textContent = questionsToday;
        if (overallAccuracy) overallAccuracy.textContent = `${questionsToday ? Math.round(100 * correctToday / questionsToday) : 0}%`;

        const todayStreak = document.getElementById("dashboard-current-streak");
        const weeklyConsistency = document.getElementById("dashboard-weekly-consistency");
        const totalStudyTime = document.getElementById("dashboard-total-study-time");
        if (todayStreak) todayStreak.textContent = `${Number(routines.current_streak || 0)} ${Number(routines.current_streak || 0) === 1 ? "day" : "days"}`;
        if (weeklyConsistency) weeklyConsistency.textContent = `${Number(routines.weekly_consistency || 0)}%`;
        if (totalStudyTime) totalStudyTime.textContent = rkFormatStudyMinutes(Number((data.study || {}).study_minutes || 0));

        const priorities = document.getElementById("dashboard-priorities");
        if (priorities) {
            const entries = [
                ...(routines.pending_habits || []).map(name => ({ label: "Habit", title: name })),
                ...(routines.pending_tasks || []).map(name => ({ label: "Task", title: name })),
                ...(routines.active_goals || []).map(goal => ({ label: `Goal · ${Number(goal.progress || 0)}%`, title: goal.title }))
            ].slice(0, 5);
            priorities.innerHTML = entries.length
                ? entries.map(entry => `<div class="dashboard-priority-row"><span>${rkEscapeHtml(entry.label)}</span><strong>${rkEscapeHtml(entry.title)}</strong></div>`).join("")
                : '<p class="dashboard-support-copy">Nothing is waiting in your routines.</p>';
        }

        const greeting = document.getElementById("dashboard-greeting");
        if (greeting && rkCurrentProfile) greeting.textContent = `Welcome, ${rkCurrentProfile.name}.`;

        console.log("RK OS dashboard data:", data);

    } catch (error) {

        console.error(
            "Failed to load dashboard data:",
            error
        );

    }
}

function rkRenderRoutineSummary(summary) {
    const habitCompletion = document.getElementById("routine-habit-completion");
    const taskCompletion = document.getElementById("routine-task-completion");
    const currentStreak = document.getElementById("routine-current-streak");
    const weeklyConsistency = document.getElementById("routine-weekly-consistency");
    if (habitCompletion) habitCompletion.textContent = `${Number(summary.habits?.completed_today || 0)} / ${Number(summary.habits?.total || 0)}`;
    if (taskCompletion) taskCompletion.textContent = `${Number(summary.tasks?.completed || 0)} / ${Number(summary.tasks?.total || 0)}`;
    if (currentStreak) currentStreak.textContent = `${Number(summary.current_streak || 0)} ${Number(summary.current_streak || 0) === 1 ? "day" : "days"}`;
    if (weeklyConsistency) weeklyConsistency.textContent = `${Number(summary.weekly_consistency || 0)}%`;
}

async function rkLoadRoutinesSummary() {
    try {
        const response = await fetch("/api/routines/summary");
        if (!response.ok) throw new Error("Failed to load routines summary");
        const summary = await response.json();
        rkRenderRoutineSummary(summary);
        return summary;
    } catch (error) {
        console.error("RK OS: Failed to load routines summary:", error);
        return null;
    }
}

async function rkLoadProfile() {
    try {
        const [profileResponse, progressResponse] = await Promise.all([
            fetch("/api/profile"),
            fetch("/api/progress")
        ]);
        if (!profileResponse.ok || !progressResponse.ok) throw new Error("Failed to load profile");
        const [profile, progress] = await Promise.all([profileResponse.json(), progressResponse.json()]);
        rkCurrentProfile = profile;
        document.getElementById("profile-name").value = profile.name || "RK User";
        document.getElementById("profile-bio").value = profile.bio || "";
        document.getElementById("profile-study-target").value = Number(profile.study_target || 120);
        document.getElementById("profile-exam-target").value = profile.exam_target || "SSC CGL";
        document.getElementById("profile-preferences").value = profile.preferences || "";
        document.getElementById("profile-assistant-preferences").value = profile.assistant_preferences || "";
        document.getElementById("profile-display-name").textContent = profile.name || "RK User";
        document.getElementById("profile-display-bio").textContent = profile.bio || "Your personal study profile.";
        document.getElementById("profile-avatar").textContent = String(profile.name || "RK").split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase();
        document.getElementById("profile-current-streak").textContent = `${Number(progress.consistency?.current_streak || 0)} days`;
        document.getElementById("profile-total-study-time").textContent = rkFormatStudyMinutes(Number((progress.study || {}).study_minutes || 0));
        const routineSummary = await fetch("/api/routines/summary").then(response => response.ok ? response.json() : null).catch(() => null);
        if (routineSummary) document.getElementById("profile-current-streak").textContent = `${Number(routineSummary.current_streak || 0)} ${Number(routineSummary.current_streak || 0) === 1 ? "day" : "days"}`;
        const completedRoutines = routineSummary
            ? Number(routineSummary.habits.completed_today || 0) + Number(routineSummary.tasks.completed || 0) + Number(routineSummary.goals.completed || 0)
            : 0;
        document.getElementById("profile-routines-completed").textContent = completedRoutines;
        const quizAccuracy = Number((progress.quiz || {}).accuracy || 0);
        const practiceAccuracy = Number((progress.practice || {}).accuracy || 0);
        document.getElementById("profile-study-accuracy").textContent = `${quizAccuracy || practiceAccuracy}%`;
        const greeting = document.getElementById("dashboard-greeting");
        if (greeting) greeting.textContent = `Welcome, ${profile.name || "RK User"}.`;
    } catch (error) {
        console.error("RK OS: Failed to load profile:", error);
    }
}

async function rkSaveProfile() {
    const status = document.getElementById("profile-save-status");
    const payload = {
        name: document.getElementById("profile-name").value,
        bio: document.getElementById("profile-bio").value,
        study_target: Number(document.getElementById("profile-study-target").value || 120),
        exam_target: document.getElementById("profile-exam-target").value,
        preferences: document.getElementById("profile-preferences").value,
        assistant_preferences: document.getElementById("profile-assistant-preferences").value
    };
    try {
        const response = await fetch("/api/profile", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const profile = await response.json();
        if (!response.ok) throw new Error(profile.detail || "Unable to save profile");
        if (status) status.textContent = "Profile saved.";
        await rkLoadProfile();
    } catch (error) {
        if (status) status.textContent = error.message || "Unable to save profile.";
    }
}

function rkAppendAssistantMessage(role, content, createdAt) {
    const conversation = document.getElementById("assistant-conversation");
    if (!conversation) return;
    const message = document.createElement("article");
    message.className = `assistant-message ${role === "user" ? "assistant-message-user" : "assistant-message-rk"}`;
    const speaker = document.createElement("strong");
    speaker.textContent = role === "user" ? "You" : "RK";
    const text = document.createElement("p");
    text.textContent = content;
    message.append(speaker, text);
    if (createdAt) {
        const time = document.createElement("time");
        time.textContent = rkFormatRevisionDate(createdAt);
        message.appendChild(time);
    }
    conversation.appendChild(message);
    conversation.scrollTop = conversation.scrollHeight;
}

async function rkLoadAssistantHistory() {
    try {
        const historyResponse = await fetch("/api/assistant/history?limit=40");
        if (!historyResponse.ok) throw new Error("Failed to load assistant history");
        const history = await historyResponse.json();
        const actions = history.slice(-8);
        const conversation = document.getElementById("assistant-conversation");
        if (conversation) {
            conversation.innerHTML = "";
            if (!history.length) rkAppendAssistantMessage("assistant", "How can I help you today?");
            history.forEach(message => rkAppendAssistantMessage(message.role, message.content, message.created_at));
        }
        const actionList = document.getElementById("assistant-recent-actions");
        if (actionList) {
            const assistantMessages = actions.filter(message => message.role === "assistant" && message.action);
            actionList.innerHTML = assistantMessages.length
                ? assistantMessages.map(message => `<div class="assistant-action-row"><span>${rkEscapeHtml((message.action || "").replaceAll("_", " "))}</span><strong>${rkEscapeHtml(message.content)}</strong></div>`).join("")
                : '<p class="dashboard-support-copy">Your RK actions will appear here.</p>';
        }
        const firstMessage = document.querySelector(".assistant-message-rk p");
        if (rkCurrentProfile && firstMessage && firstMessage.textContent === "How can I help you today?") {
            firstMessage.textContent = `How can I help you today, ${rkCurrentProfile.name}?`;
        }
    } catch (error) {
        console.error("RK OS: Failed to load assistant history:", error);
    }
}

async function rkSendAssistantMessage() {
    const input = document.getElementById("assistant-input");
    const command = input ? input.value.trim() : "";
    if (!command) return;
    input.value = "";
    const submit = document.querySelector("#assistant-form button[type='submit']");
    if (submit) submit.disabled = true;
    try {
        const response = await fetch("/api/assistant/command", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "RK Assistant could not process that request.");
        await rkLoadAssistantHistory();
        await rkRunAssistantAction(result.action, result.data);
        await Promise.all([loadDashboardData(), rkLoadRoutinesSummary()]);
        if (["create_task", "complete_task", "delete_task"].includes(result.action)) await rkLoadTasks();
        if (["create_habit", "complete_habit", "delete_habit"].includes(result.action)) await rkLoadHabits();
        if (["create_goal", "update_goal"].includes(result.action)) await rkLoadGoals();
    } catch (error) {
        rkAppendAssistantMessage("assistant", error.message || "I couldn't connect to RK OS.");
    } finally {
        if (submit) submit.disabled = false;
    }
}

async function rkRunAssistantAction(action, data) {
    if (action === "open_learn" || action === "show_study_plan") {
        rkNavigateToSection("learn");
    } else if (action === "open_revision") {
        rkNavigateToSection("learn");
        await rkOpenRevision();
    } else if (action === "start_practice") {
        rkNavigateToSection("learn");
        await rkOpenPracticeCurrent();
    } else if (action === "start_quiz") {
        rkNavigateToSection("learn");
        await rkOpenQuizCurrent();
    } else if (action === "start_focus_timer") {
        rkNavigateToSection("learn");
        rkSetFocusPreset(Number((data || {}).minutes || 25));
        await rkStartFocusTimer();
    }
}

function rkAssistantQuickAction(command) {
    const input = document.getElementById("assistant-input");
    if (input) input.value = command;
    rkSendAssistantMessage();
}

async function rkOpenStudyLibrary() {
    const library = document.getElementById("learn-library");
    if (library) library.open = true;
    if (!rkStudyCatalog.subjects.length) await rkLoadStudyPage();
    document.getElementById("study-overview")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function rkOpenPracticeCurrent() {
    if (!rkStudyCatalog.subjects.length) await rkLoadStudyPage();
    await rkOpenPractice(rkStudySelection.subjectId, rkStudySelection.topicId);
}

async function rkOpenQuizCurrent() {
    if (!rkStudyCatalog.subjects.length) await rkLoadStudyPage();
    await rkOpenQuizStudio(rkStudySelection.subjectId, rkStudySelection.topicId);
}


const rkStudySelection = {
    subjectId: null,
    topicId: null
};

const rkStudyCatalog = {
    subjects: [],
    topics: []
};

const rkPracticeState = {
    questions: [],
    index: 0,
    attempts: [],
    filters: { subjectId: null, topicId: null, difficulty: "Mixed" }
};

const rkQuizState = {
    session: null,
    index: 0,
    requestedCount: 10,
    results: [],
    filters: { subjectId: null, topicId: null, difficulty: "Mixed" }
};

const rkStudyTimerState = {
    currentSubjectId: null,
    currentTopicId: null,
    sessionStartedAt: null,
    startedAt: null,
    running: false,
    elapsedSeconds: 0,
    targetSeconds: 0,
    timerId: null
};

let rkFocusPresetMinutes = 25;
let rkCurrentProfile = null;

const RK_STUDY_TIMER_KEY = "rk_study_timer_state";

function rkFormatStudyMinutes(minutes) {
    if (!minutes && minutes !== 0) return "0m";
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    const remainder = minutes % 60;
    return remainder ? `${hours}h ${remainder}m` : `${hours}h`;
}

function rkFormatStudyClock(totalSeconds) {
    const safeSeconds = Math.max(0, Number(totalSeconds) || 0);
    const minutes = Math.floor(safeSeconds / 60);
    const seconds = safeSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function rkStudyCurrentElapsedSeconds() {
    if (!rkStudyTimerState.running || !rkStudyTimerState.startedAt) {
        return Math.max(0, Number(rkStudyTimerState.elapsedSeconds) || 0);
    }

    const startedMs = new Date(rkStudyTimerState.startedAt).getTime();
    const elapsed = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
    return Math.max(0, Number(rkStudyTimerState.elapsedSeconds) + elapsed);
}

function rkStudySyncTimerDisplay() {
    const timerDisplays = [
        document.getElementById("study-timer-value"),
        document.getElementById("learn-focus-timer-value")
    ].filter(Boolean);
    const timerStatuses = [
        document.getElementById("study-timer-status"),
        document.getElementById("learn-focus-status")
    ].filter(Boolean);
    const currentElapsed = rkStudyCurrentElapsedSeconds();
    const targetSeconds = Number(rkStudyTimerState.targetSeconds || 0);
    const visibleTargetSeconds = targetSeconds > 0
        ? targetSeconds
        : (!rkStudyTimerState.currentSubjectId ? rkFocusPresetMinutes * 60 : 0);
    const timerSeconds = visibleTargetSeconds > 0
        ? Math.max(0, visibleTargetSeconds - currentElapsed)
        : currentElapsed;

    timerDisplays.forEach(timerDisplay => {
        timerDisplay.textContent = rkFormatStudyClock(timerSeconds);
    });

    timerStatuses.forEach(timerStatus => {
        const selectedSession = rkStudyTimerState.currentSubjectId === rkStudySelection.subjectId &&
            rkStudyTimerState.currentTopicId === rkStudySelection.topicId;
        timerStatus.textContent = !rkStudyTimerState.currentSubjectId
            ? (targetSeconds ? `${rkFocusPresetMinutes}-minute focus` : "Ready")
            : (!selectedSession ? "Session active on another topic" : (rkStudyTimerState.running ? "Running" : "Paused"));
    });
}

function rkStudySaveTimerState() {
    const { timerId, ...state } = rkStudyTimerState;
    if (!state.currentSubjectId && !state.currentTopicId && !state.sessionStartedAt && !state.running) {
        localStorage.removeItem(RK_STUDY_TIMER_KEY);
        return;
    }

    localStorage.setItem(RK_STUDY_TIMER_KEY, JSON.stringify(state));
}

function rkStudyRestoreTimerState() {
    try {
        const saved = JSON.parse(localStorage.getItem(RK_STUDY_TIMER_KEY) || "null");

        if (!saved) {
            return;
        }

        Object.assign(rkStudyTimerState, saved);

        if (saved.running && saved.startedAt) {
            const restored = Math.max(0, Number(saved.elapsedSeconds) || 0);
            const offset = Math.max(0, Math.floor((Date.now() - new Date(saved.startedAt).getTime()) / 1000));
            rkStudyTimerState.elapsedSeconds = restored + offset;
            rkStudyTimerState.startedAt = new Date().toISOString();
            rkStudyTimerState.running = true;
            rkStudyStartInterval();
        }

        rkStudySyncTimerDisplay();
    } catch (error) {
        console.error("RK OS: Failed to restore study timer state:", error);
    }
}

function rkStudyStartInterval() {
    if (rkStudyTimerState.timerId) {
        clearInterval(rkStudyTimerState.timerId);
    }

    rkStudyTimerState.timerId = setInterval(() => {
        if (!rkStudyTimerState.running || !rkStudyTimerState.startedAt) {
            return;
        }

        rkStudyTimerState.elapsedSeconds = rkStudyCurrentElapsedSeconds();
        rkStudyTimerState.startedAt = new Date().toISOString();
        rkStudySaveTimerState();
        rkStudySyncTimerDisplay();
        if (rkStudyTimerState.targetSeconds > 0 && rkStudyTimerState.elapsedSeconds >= rkStudyTimerState.targetSeconds) {
            rkStudyTimerState.elapsedSeconds = rkStudyTimerState.targetSeconds;
            rkStudyTimerState.running = false;
            rkStudyTimerState.startedAt = null;
            clearInterval(rkStudyTimerState.timerId);
            rkStudyTimerState.timerId = null;
            rkStudySaveTimerState();
            rkStudySyncTimerDisplay();
            rkStudyEndSession();
        }
    }, 1000);
}

function rkStudyResetTimerState() {
    if (rkStudyTimerState.timerId) {
        clearInterval(rkStudyTimerState.timerId);
        rkStudyTimerState.timerId = null;
    }

    rkStudyTimerState.currentSubjectId = null;
    rkStudyTimerState.currentTopicId = null;
    rkStudyTimerState.sessionStartedAt = null;
    rkStudyTimerState.startedAt = null;
    rkStudyTimerState.running = false;
    rkStudyTimerState.elapsedSeconds = 0;
    rkStudyTimerState.targetSeconds = 0;
    localStorage.removeItem(RK_STUDY_TIMER_KEY);
    rkStudySyncTimerDisplay();
}

function rkSetFocusPreset(minutes) {
    if (rkStudyTimerState.currentSubjectId) return;
    rkFocusPresetMinutes = Math.max(1, Number(minutes) || 25);
    rkStudyTimerState.targetSeconds = rkFocusPresetMinutes * 60;
    rkStudyTimerState.elapsedSeconds = 0;
    document.querySelectorAll(".focus-presets button").forEach(button => {
        button.classList.toggle("active", Number(button.dataset.minutes) === rkFocusPresetMinutes);
    });
    rkStudySyncTimerDisplay();
}

async function rkStartFocusTimer() {
    if (rkStudyTimerState.running) return;
    if (rkStudyTimerState.currentSubjectId && !rkStudyTimerState.running) {
        rkStudyTimerState.running = true;
        rkStudyTimerState.startedAt = new Date().toISOString();
        rkStudyStartInterval();
        rkStudySaveTimerState();
        rkStudySyncTimerDisplay();
        return;
    }
    if (!rkStudySelection.subjectId || !rkStudySelection.topicId) {
        await rkLoadStudyPage();
    }
    rkStudyTimerState.targetSeconds = rkFocusPresetMinutes * 60;
    await rkStudyStartTimer(rkStudySelection.subjectId, rkStudySelection.topicId);
}

function rkResetFocusTimer() {
    if (rkStudyTimerState.timerId) clearInterval(rkStudyTimerState.timerId);
    rkStudyTimerState.timerId = null;
    rkStudyTimerState.currentSubjectId = null;
    rkStudyTimerState.currentTopicId = null;
    rkStudyTimerState.sessionStartedAt = null;
    rkStudyTimerState.startedAt = null;
    rkStudyTimerState.running = false;
    rkStudyTimerState.elapsedSeconds = 0;
    rkStudyTimerState.targetSeconds = rkFocusPresetMinutes * 60;
    localStorage.removeItem(RK_STUDY_TIMER_KEY);
    rkStudySyncTimerDisplay();
}

async function rkStudyStartTimer(subjectId, topicId) {
    const safeSubjectId = Number(subjectId);
    const safeTopicId = Number(topicId);

    if (!safeSubjectId || !safeTopicId) {
        alert("Select a subject and topic before starting a study session.");
        return;
    }

    if (rkStudyTimerState.currentSubjectId && (
        rkStudyTimerState.currentSubjectId !== safeSubjectId ||
        rkStudyTimerState.currentTopicId !== safeTopicId
    )) {
        alert("End the current study session before starting another topic.");
        return;
    }

    rkStudySelection.subjectId = safeSubjectId;
    rkStudySelection.topicId = safeTopicId;
    rkStudyTimerState.currentSubjectId = safeSubjectId;
    rkStudyTimerState.currentTopicId = safeTopicId;
    rkStudyTimerState.sessionStartedAt = rkStudyTimerState.sessionStartedAt || new Date().toISOString();
    rkStudyTimerState.running = true;
    rkStudyTimerState.startedAt = new Date().toISOString();
    rkStudyStartInterval();
    rkStudySaveTimerState();
    rkStudySyncTimerDisplay();
    rkLoadStudyPage();
}

function rkStudyPauseTimer() {
    if (!rkStudyTimerState.currentSubjectId || !rkStudyTimerState.currentTopicId) {
        return;
    }

    rkStudyTimerState.elapsedSeconds = rkStudyCurrentElapsedSeconds();
    rkStudyTimerState.running = false;
    rkStudyTimerState.startedAt = null;
    if (rkStudyTimerState.timerId) {
        clearInterval(rkStudyTimerState.timerId);
        rkStudyTimerState.timerId = null;
    }
    rkStudySaveTimerState();
    rkStudySyncTimerDisplay();
    rkLoadStudyPage();
}

async function rkStudyEndSession() {
    if (!rkStudyTimerState.currentSubjectId || !rkStudyTimerState.currentTopicId) {
        alert("There is no active study session to save.");
        return;
    }

    const elapsedSeconds = rkStudyCurrentElapsedSeconds();
    const startedAt = rkStudyTimerState.sessionStartedAt || new Date().toISOString();
    const completedAt = new Date().toISOString();
    const durationMinutes = Math.max(0, Math.floor(elapsedSeconds / 60));

    try {
        const response = await fetch("/api/study/sessions", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                subject_id: rkStudyTimerState.currentSubjectId,
                topic_id: rkStudyTimerState.currentTopicId,
                session_type: "study",
                started_at: startedAt,
                completed_at: completedAt,
                duration_minutes: durationMinutes
            })
        });

        if (!response.ok) {
            throw new Error("Failed to save study session");
        }

        rkStudyResetTimerState();
        await rkRefreshRKOSData({ study: true });

    } catch (error) {
        console.error("RK OS: Failed to end study session:", error);
        alert("Unable to save the study session. Please try again.");
    }
}

async function rkLoadStudyPage() {
    try {
        const [subjectsResponse, overviewResponse, topicsResponse, practiceStatsResponse, quizStatsResponse] = await Promise.all([
            fetch("/api/study/subjects"),
            fetch("/api/study/overview"),
            fetch("/api/study/topics"),
            fetch("/api/practice/statistics"),
            fetch("/api/quiz/statistics")
        ]);
        if (!subjectsResponse.ok || !overviewResponse.ok || !topicsResponse.ok || !practiceStatsResponse.ok || !quizStatsResponse.ok) {
            throw new Error("Failed to load study data");
        }

        const [subjects, overview, topics, practiceStats, quizStats] = await Promise.all([
            subjectsResponse.json(),
            overviewResponse.json(),
            topicsResponse.json(),
            practiceStatsResponse.json(),
            quizStatsResponse.json()
        ]);

        if (!subjects.length) {
            const overviewContainer = document.getElementById("study-overview");
            if (overviewContainer) {
                overviewContainer.innerHTML = `
                    <div class="learn-card learn-feature">
                        <div class="learn-card-header">
                            <div>
                                <p class="eyebrow">STUDY OVERVIEW</p>
                                <h3>No study data yet</h3>
                            </div>
                        </div>
                        <p class="learn-summary">Study subjects and topics will appear here once the database is populated.</p>
                    </div>
                `;
            }
            return;
        }

        if (!rkStudySelection.subjectId || !subjects.some(subject => Number(subject.id) === Number(rkStudySelection.subjectId))) {
            rkStudySelection.subjectId = Number(subjects[0].id);
        }

        const selectedSubject = subjects.find(subject => Number(subject.id) === Number(rkStudySelection.subjectId)) || subjects[0];
        const subjectTopics = topics.filter(topic => Number(topic.subject_id) === Number(selectedSubject.id));

        if (!rkStudySelection.topicId || !subjectTopics.some(topic => Number(topic.id) === Number(rkStudySelection.topicId))) {
            rkStudySelection.topicId = subjectTopics[0] ? Number(subjectTopics[0].id) : null;
        }

        const selectedTopic = subjectTopics.find(topic => Number(topic.id) === Number(rkStudySelection.topicId)) || subjectTopics[0] || null;

        rkStudyCatalog.subjects = subjects;
        rkStudyCatalog.topics = topics;
        const currentSubjectElement = document.getElementById("learn-current-subject");
        const currentTopicElement = document.getElementById("learn-current-topic");
        const recommendationElement = document.getElementById("learn-study-recommendation");
        if (currentSubjectElement) currentSubjectElement.textContent = selectedSubject.name;
        if (currentTopicElement) currentTopicElement.textContent = selectedTopic ? selectedTopic.name : "Select a topic";
        const dashboardStudyElement = document.getElementById("dashboard-current-study");
        const dashboardTopicElement = document.getElementById("dashboard-study-topic");
        if (dashboardStudyElement) dashboardStudyElement.textContent = selectedSubject.name;
        if (dashboardTopicElement) dashboardTopicElement.textContent = selectedTopic ? selectedTopic.name : "Select a topic in Learn.";
        if (recommendationElement) recommendationElement.textContent = selectedTopic
            ? (selectedTopic.description || "Continue your current SSC CGL topic.")
            : "Browse a subject and topic to continue your study plan.";

        let topicDetail = null;
        let notes = [];
        if (selectedTopic) {
            const [topicResponse, notesResponse] = await Promise.all([
                fetch(`/api/study/topics/${selectedTopic.id}`),
                fetch(`/api/study/notes?subject_id=${selectedSubject.id}&topic_id=${selectedTopic.id}`)
            ]);
            if (!topicResponse.ok || !notesResponse.ok) {
                throw new Error("Failed to load topic details and notes");
            }
            [topicDetail, notes] = await Promise.all([
                topicResponse.json(),
                notesResponse.json()
            ]);
        }

        rkRenderStudyOverview(overview, practiceStats, quizStats);
        rkRenderSubjectCards(subjects, topics, selectedSubject.id);
        rkRenderStudyDetail(selectedSubject, subjectTopics, selectedTopic, topicDetail, notes);
        rkRenderStudySessionHistory(overview.recent_sessions || []);
    } catch (error) {
        console.error("RK OS: Failed to load study page:", error);
    }
}

function rkRenderStudyOverview(overview, practiceStats = {}, quizStats = {}) {
    const container = document.getElementById("study-overview");
    if (!container) return;

    const totalMinutes = Number(overview.today_study_minutes || 0);
    const totalSessions = Number(overview.today_sessions || 0);
    const totalSubjects = Number(overview.total_subjects || 0);
    const topicsStudied = Number(overview.topics_studied_today || 0);
    const practiceQuestions = Number(practiceStats.total_questions || 0);
    const practiceCorrect = Number(practiceStats.correct || 0);
    const practiceAccuracy = Number(practiceStats.accuracy || 0);
    const weakTopics = Number(practiceStats.weak_topics || 0);
    const quizAttempts = Number(quizStats.attempts || 0);
    const quizQuestions = Number(quizStats.questions || 0);
    const quizAccuracy = Number(quizStats.accuracy || 0);
    const quizBestAccuracy = Number(quizStats.best_accuracy || 0);
    const practiceToday = practiceStats.today || {};
    const quizToday = quizStats.today || {};
    const todayQuestions = Number(practiceToday.total_questions || 0) + Number(quizToday.questions || 0);
    const todayCorrect = Number(practiceToday.correct || 0) + Number(quizToday.correct || 0);
    const learnStudyTime = document.getElementById("learn-today-study-time");
    const learnQuestions = document.getElementById("learn-today-questions");
    const learnAccuracy = document.getElementById("learn-today-accuracy");
    if (learnStudyTime) learnStudyTime.textContent = rkFormatStudyMinutes(totalMinutes);
    if (learnQuestions) learnQuestions.textContent = todayQuestions;
    if (learnAccuracy) learnAccuracy.textContent = `${todayQuestions ? Math.round(100 * todayCorrect / todayQuestions) : 0}%`;

    container.innerHTML = `
        <div class="learn-card learn-feature">
            <div class="learn-card-header">
                <div>
                    <p class="eyebrow">STUDY OVERVIEW</p>
                    <h3>Today's Learning Flow</h3>
                </div>
            </div>

            <div class="learn-metrics">
                <div class="learn-metric">
                    <span>Today's study time</span>
                    <strong>${totalMinutes ? rkFormatStudyMinutes(totalMinutes) : "0m"}</strong>
                </div>
                <div class="learn-metric">
                    <span>Topics studied</span>
                    <strong>${topicsStudied}</strong>
                </div>
                <div class="learn-metric">
                    <span>Today's sessions</span>
                    <strong>${totalSessions}</strong>
                </div>
                <div class="learn-metric">
                    <span>Streak</span>
                    <strong>${Number(overview.current_streak || 0)} day${Number(overview.current_streak || 0) === 1 ? "" : "s"}</strong>
                </div>
                <div class="learn-metric">
                    <span>Practice questions</span>
                    <strong>${practiceQuestions}</strong>
                </div>
                <div class="learn-metric">
                    <span>Practice accuracy</span>
                    <strong>${practiceAccuracy}%</strong>
                </div>
            </div>
        </div>

        <div class="learn-card">
            <div class="learn-card-header">
                <div>
                    <p class="eyebrow">STATUS</p>
                    <h3>Study Snapshot</h3>
                </div>
            </div>
            <ul class="learn-list compact">
                <li><span class="list-pill">Subjects</span> ${totalSubjects} available</li>
                <li><span class="list-pill">Topics studied</span> ${topicsStudied} today</li>
                <li><span class="list-pill">Today</span> ${totalSessions ? `${totalSessions} session${totalSessions === 1 ? "" : "s"}` : "No activity yet"}</li>
                <li><span class="list-pill">Correct</span> ${practiceCorrect} answers</li>
                <li><span class="list-pill">Weak topics</span> ${weakTopics}</li>
                <li><span class="list-pill">Quiz Attempts</span> ${quizAttempts}</li>
                <li><span class="list-pill">Quiz Questions</span> ${quizQuestions}</li>
                <li><span class="list-pill">Quiz Accuracy</span> ${quizAccuracy}%</li>
                <li><span class="list-pill">Best Accuracy</span> ${quizBestAccuracy}%</li>
            </ul>
        </div>
    `;
}

function rkRenderSubjectCards(subjects, topics, selectedSubjectId) {
    const container = document.getElementById("study-overview");
    if (!container) return;

    const subjectGrid = document.createElement("div");
    subjectGrid.className = "subject-grid";

    subjects.forEach((subject) => {
        const topicCount = topics.filter(topic => Number(topic.subject_id) === Number(subject.id)).length;
        const button = document.createElement("button");
        button.type = "button";
        button.className = `subject-card ${Number(selectedSubjectId) === Number(subject.id) ? "active" : ""}`;
        button.onclick = () => {
            rkStudySelection.subjectId = Number(subject.id);
            rkStudySelection.topicId = null;
            rkLoadStudyPage();
        };

        button.innerHTML = `
            <div class="subject-topline">${rkEscapeHtml(subject.name)}</div>
            <p class="subject-description">${rkEscapeHtml(subject.description || "Core SSC foundation topics.")}</p>
            <div class="subject-footer"><span>${topicCount} topics</span><strong>Open Subject</strong></div>
        `;

        subjectGrid.appendChild(button);
    });

    if (!container.querySelector(".subject-grid")) {
        container.appendChild(subjectGrid);
    } else {
        container.querySelector(".subject-grid").replaceWith(subjectGrid);
    }
}

function rkRenderStudyDetail(subject, subjectTopics, selectedTopic, topicDetail, notes) {
    const panel = document.getElementById("study-detail-panel");
    if (!panel) return;

    const hasCurrentSession = Boolean(rkStudyTimerState.currentSubjectId && rkStudyTimerState.currentTopicId);
    const selectedSession = hasCurrentSession && rkStudyTimerState.currentSubjectId === Number(subject.id) && rkStudyTimerState.currentTopicId === Number(selectedTopic ? selectedTopic.id : 0);
    const startButtonLabel = selectedSession
        ? (rkStudyTimerState.running ? "Session Running" : "Resume Session")
        : "Start Study Session";
    const startDisabled = !selectedTopic || (hasCurrentSession && !selectedSession) || (selectedSession && rkStudyTimerState.running);

    const topicButtons = (subjectTopics || []).map((topic) => {
        const isActive = selectedTopic && Number(topic.id) === Number(selectedTopic.id);
        return `
            <button
                type="button"
                class="study-topic-item ${isActive ? "active" : ""}"
                onclick="rkStudySelection.subjectId = ${Number(subject.id)}; rkStudySelection.topicId = ${Number(topic.id)}; rkLoadStudyPage();"
            >
                <span>○</span>
                ${rkEscapeHtml(topic.name)}
            </button>
        `;
    }).join("");

    const timerValue = hasCurrentSession
        ? rkFormatStudyClock(rkStudyCurrentElapsedSeconds())
        : "00:00";

    const timerState = selectedSession
        ? (rkStudyTimerState.running ? "Running" : "Paused")
        : (hasCurrentSession ? "Session active on another topic" : "Ready");
    const noteCards = (notes || []).map(note => `
        <button class="study-note-card" type="button" onclick="rkOpenStudyNote(${Number(note.id)})">
            <span class="study-note-label">${rkEscapeHtml(note.title.startsWith("Demo:") ? "DEMO CONTENT" : "STUDY NOTE")}</span>
            <strong>${rkEscapeHtml(note.title)}</strong>
            <span class="study-note-action">Open note</span>
        </button>
    `).join("");
    const topicProgress = topicDetail
        ? `${Number(topicDetail.study_sessions || 0)} sessions · ${rkFormatStudyMinutes(Number(topicDetail.study_minutes || 0))} studied`
        : "No study sessions yet";
    const topicAccuracy = topicDetail && Number(topicDetail.practice_questions || 0)
        ? `${Number(topicDetail.practice_accuracy || 0)}% from ${Number(topicDetail.practice_questions)} attempt${Number(topicDetail.practice_questions) === 1 ? "" : "s"}`
        : "No practice attempts yet";
    const quizTopicAccuracy = topicDetail && Number(topicDetail.quiz_questions || 0)
        ? `${Number(topicDetail.quiz_accuracy || 0)}% from ${Number(topicDetail.quiz_questions)} answer${Number(topicDetail.quiz_questions) === 1 ? "" : "s"}`
        : "No quiz answers yet";
    const lastStudied = topicDetail && topicDetail.last_studied
        ? new Date(topicDetail.last_studied).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })
        : "Not studied yet";

    panel.innerHTML = `
        <div class="study-detail-card">
            <div class="study-detail-header">
                <div>
                    <p class="eyebrow">SUBJECT</p>
                    <h3>${rkEscapeHtml(subject.name)}</h3>
                </div>
                <span class="study-progress-badge">${rkEscapeHtml(topicProgress)}</span>
            </div>

            <div class="study-selected-topic">
                <p class="eyebrow">SELECTED TOPIC</p>
                <h4>${selectedTopic ? rkEscapeHtml(selectedTopic.name) : "Choose a topic"}</h4>
                <p>${selectedTopic ? rkEscapeHtml(selectedTopic.description || "") : "Select a topic to see its notes and study controls."}</p>
                <div class="study-topic-performance">
                    <span>Practice accuracy: <strong>${rkEscapeHtml(topicAccuracy)}</strong></span>
                    <span>Quiz accuracy: <strong>${rkEscapeHtml(quizTopicAccuracy)}</strong></span>
                    <span>Last studied: <strong>${rkEscapeHtml(lastStudied)}</strong></span>
                </div>
            </div>

            <div class="study-detail-content">
                <div class="study-topic-panel">
                    <div class="study-detail-subtitle">Topics</div>
                    <div class="study-topic-list">${topicButtons || '<div class="study-empty-state">No topics available for this subject yet.</div>'}</div>
                </div>

                <div class="study-notes-panel">
                    <div class="study-detail-subtitle">Available notes</div>
                    <div class="study-note-list">${noteCards || '<p class="study-empty-state">No notes are available for this topic yet.</p>'}</div>
                </div>

                <div class="study-timer-panel">
                    <div class="study-detail-subtitle">Study</div>
                    <div id="study-timer-value" class="study-timer-value">${timerValue}</div>
                    <div id="study-timer-status" class="study-timer-status">${timerState}</div>

                    <div class="study-timer-actions">
                        <button class="primary-button" type="button" ${startDisabled ? "disabled" : ""} onclick="rkStudyStartTimer(${Number(subject.id)}, ${selectedTopic ? Number(selectedTopic.id) : 0})">${startButtonLabel}</button>
                        <button class="secondary-button" type="button" ${!hasCurrentSession || !rkStudyTimerState.running ? "disabled" : ""} onclick="rkStudyPauseTimer()">Pause</button>
                        <button class="danger-button" type="button" ${!hasCurrentSession ? "disabled" : ""} onclick="rkStudyEndSession()">End Session</button>
                    </div>
                    <div class="study-secondary-actions">
                        <button class="practice-launch-button" type="button" ${!selectedTopic ? "disabled" : ""} onclick="rkOpenPractice(${Number(subject.id)}, ${selectedTopic ? Number(selectedTopic.id) : 0})">Start Practice</button>
                        <button class="revision-launch-button" type="button" onclick="rkOpenRevision()">My Revision</button>
                        <button class="quiz-launch-button" type="button" ${!selectedTopic ? "disabled" : ""} onclick="rkOpenQuizStudio(${Number(subject.id)}, ${selectedTopic ? Number(selectedTopic.id) : 0})">Start Quiz</button>
                        <button type="button" disabled>Mock Test <span>Coming next</span></button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function rkRenderStudySessionHistory(sessions) {
    const container = document.getElementById("study-session-history");
    if (!container) return;

    const rows = sessions.map(session => {
        const sessionDate = session.completed_at || session.started_at;
        const formattedDate = sessionDate
            ? new Date(sessionDate).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })
            : "Date unavailable";
        return `
            <div class="study-session-row">
                <div>
                    <strong>${rkEscapeHtml(session.topic_name || "Study session")}</strong>
                    <span>${rkEscapeHtml(session.subject_name || "Subject unavailable")}</span>
                </div>
                <span>${rkFormatStudyMinutes(Number(session.duration_minutes || 0))}</span>
                <time>${rkEscapeHtml(formattedDate)}</time>
            </div>
        `;
    }).join("");

    container.innerHTML = `
        <div class="study-history-heading">
            <div><p class="eyebrow">YOUR ACTIVITY</p><h3>Recent Study Sessions</h3></div>
        </div>
        <div class="study-session-list">${rows || '<p class="study-empty-state">No study sessions yet.</p>'}</div>
    `;
}

async function rkOpenStudyNote(noteId) {
    try {
        const response = await fetch(`/api/study/notes/${Number(noteId)}`);
        if (!response.ok) throw new Error("Failed to open study note");
        const note = await response.json();
        document.getElementById("study-note-title").textContent = note.title;
        document.getElementById("study-note-content").textContent = note.content;
        document.getElementById("study-note-dialog").showModal();
    } catch (error) {
        console.error("RK OS: Failed to open study note:", error);
    }
}

function rkPracticePopulateTopics(subjectId, selectedTopicId) {
    const topicSelect = document.getElementById("practice-topic");
    if (!topicSelect) return;
    const matchingTopics = rkStudyCatalog.topics.filter(topic => Number(topic.subject_id) === Number(subjectId));
    topicSelect.innerHTML = matchingTopics.map(topic =>
        `<option value="${Number(topic.id)}">${rkEscapeHtml(topic.name)}</option>`
    ).join("");
    if (selectedTopicId && matchingTopics.some(topic => Number(topic.id) === Number(selectedTopicId))) {
        topicSelect.value = String(selectedTopicId);
    }
}

function rkPracticeSubjectChanged() {
    const subjectSelect = document.getElementById("practice-subject");
    rkPracticePopulateTopics(subjectSelect ? subjectSelect.value : null, null);
}

async function rkOpenPractice(subjectId, topicId) {
    const subjectSelect = document.getElementById("practice-subject");
    if (!subjectSelect) return;
    subjectSelect.innerHTML = rkStudyCatalog.subjects.map(subject =>
        `<option value="${Number(subject.id)}">${rkEscapeHtml(subject.name)}</option>`
    ).join("");
    subjectSelect.value = String(subjectId);
    rkPracticePopulateTopics(subjectId, topicId);
    document.getElementById("practice-difficulty").value = "Mixed";
    document.getElementById("practice-question-view").innerHTML = "";
    document.getElementById("practice-dialog").showModal();
    await rkLoadPracticeQuestionsFromFilters();
}

async function rkLoadPracticeQuestionsFromFilters() {
    const subjectId = Number(document.getElementById("practice-subject").value);
    const topicId = Number(document.getElementById("practice-topic").value);
    const difficulty = document.getElementById("practice-difficulty").value || "Mixed";
    const panel = document.getElementById("practice-question-view");
    panel.innerHTML = '<p class="study-empty-state">Loading questions...</p>';
    try {
        const query = new URLSearchParams({ subject_id: subjectId, topic_id: topicId, difficulty });
        const response = await fetch(`/api/practice/questions?${query}`);
        if (!response.ok) throw new Error("Failed to load practice questions");
        const questions = await response.json();
        rkPracticeState.questions = questions;
        rkPracticeState.index = 0;
        rkPracticeState.attempts = [];
        rkPracticeState.filters = { subjectId, topicId, difficulty };
        if (!questions.length) {
            panel.innerHTML = '<p class="study-empty-state">No questions are available for this filter yet.</p>';
            return;
        }
        rkRenderPracticeQuestion();
    } catch (error) {
        console.error("RK OS: Failed to load practice questions:", error);
        panel.innerHTML = '<p class="study-empty-state">Unable to load practice questions.</p>';
    }
}

function rkRenderPracticeQuestion() {
    const panel = document.getElementById("practice-question-view");
    const question = rkPracticeState.questions[rkPracticeState.index];
    if (!question) {
        rkRenderPracticeComplete();
        return;
    }
    const options = ["A", "B", "C", "D"].map(option => `
        <label class="practice-option" for="practice-option-${option}">
            <input id="practice-option-${option}" type="radio" name="practice-answer" value="${option}">
            <span class="practice-option-letter">${option}</span>
            <span>${rkEscapeHtml(question[`option_${option.toLowerCase()}`])}</span>
        </label>
    `).join("");
    panel.innerHTML = `
        <div class="practice-question-meta">
            <span>Question ${rkPracticeState.index + 1} of ${rkPracticeState.questions.length}</span>
            <span>${rkEscapeHtml(question.difficulty)}</span>
        </div>
        <p class="practice-question-subject">${rkEscapeHtml(question.subject_name)} / ${rkEscapeHtml(question.topic_name)}</p>
        <h4 class="practice-question-text">${rkEscapeHtml(question.question_text)}</h4>
        <div class="practice-options">${options}</div>
        <p class="practice-source">${rkEscapeHtml(question.source)}</p>
        <p id="practice-answer-error" class="practice-answer-error" role="alert"></p>
        <button class="primary-button practice-submit-button" type="button" onclick="rkSubmitPracticeAnswer()">Submit Answer</button>
    `;
}

async function rkSubmitPracticeAnswer() {
    const question = rkPracticeState.questions[rkPracticeState.index];
    const selected = document.querySelector('input[name="practice-answer"]:checked');
    const error = document.getElementById("practice-answer-error");
    const submitButton = document.querySelector(".practice-submit-button");
    if (!selected) {
        if (error) error.textContent = "Select an answer before submitting.";
        return;
    }
    if (submitButton) submitButton.disabled = true;
    try {
        const response = await fetch("/api/practice/attempts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question_id: question.id, selected_option: selected.value })
        });
        if (!response.ok) throw new Error("Failed to save practice attempt");
        const result = await response.json();
        rkPracticeState.attempts.push(result);
        rkRenderPracticeAnswer(question, result);
        await rkRefreshRKOSData({ study: true });
    } catch (requestError) {
        console.error("RK OS: Failed to submit practice answer:", requestError);
        if (error) error.textContent = "Unable to save this answer. Please try again.";
        if (submitButton) submitButton.disabled = false;
    }
}

function rkRenderPracticeAnswer(question, result) {
    const correctText = question[`option_${result.correct_option.toLowerCase()}`];
    const panel = document.getElementById("practice-question-view");
    panel.innerHTML = `
        <div class="practice-question-meta">
            <span>Question ${rkPracticeState.index + 1} of ${rkPracticeState.questions.length}</span>
            <span>${rkEscapeHtml(question.difficulty)}</span>
        </div>
        <h4 class="practice-question-text">${rkEscapeHtml(question.question_text)}</h4>
        <div class="practice-result ${result.is_correct ? "correct" : "incorrect"}">
            <strong>${result.is_correct ? "Correct" : "Incorrect"}</strong>
            <p>Correct answer: ${rkEscapeHtml(result.correct_option)}. ${rkEscapeHtml(correctText)}</p>
            <p>${rkEscapeHtml(result.explanation)}</p>
        </div>
        <p class="practice-source">${rkEscapeHtml(question.source)}</p>
        <button class="primary-button practice-submit-button" type="button" onclick="rkPracticeNextQuestion()">${rkPracticeState.index + 1 === rkPracticeState.questions.length ? "See Results" : "Next Question"}</button>
    `;
}

function rkPracticeNextQuestion() {
    rkPracticeState.index += 1;
    if (rkPracticeState.index >= rkPracticeState.questions.length) {
        rkRenderPracticeComplete();
    } else {
        rkRenderPracticeQuestion();
    }
}

function rkRenderPracticeComplete() {
    const total = rkPracticeState.attempts.length;
    const correct = rkPracticeState.attempts.filter(attempt => attempt.is_correct).length;
    const incorrect = total - correct;
    const accuracy = total ? Math.round((correct / total) * 100) : 0;
    document.getElementById("practice-question-view").innerHTML = `
        <div class="practice-complete">
            <p class="eyebrow">PRACTICE COMPLETE</p>
            <h4>Practice Complete</h4>
            <div class="practice-score-grid">
                <div><span>Questions</span><strong>${total}</strong></div>
                <div><span>Correct</span><strong>${correct}</strong></div>
                <div><span>Incorrect</span><strong>${incorrect}</strong></div>
                <div><span>Accuracy</span><strong>${accuracy}%</strong></div>
            </div>
            <div class="practice-complete-actions">
                <button class="primary-button" type="button" onclick="rkLoadPracticeQuestionsFromFilters()">Practice Again</button>
                <button class="secondary-button" type="button" onclick="rkClosePracticeToTopic()">Back to Topic</button>
            </div>
        </div>
    `;
}

function rkClosePracticeToTopic() {
    document.getElementById("practice-dialog").close();
    rkLoadStudyPage();
}

function rkQuizPopulateTopics(subjectId, selectedTopicId) {
    const topicSelect = document.getElementById("quiz-topic");
    if (!topicSelect) return;
    const matchingTopics = rkStudyCatalog.topics.filter(topic => Number(topic.subject_id) === Number(subjectId));
    topicSelect.innerHTML = '<option value="all">All Topics</option>' + matchingTopics.map(topic =>
        `<option value="${Number(topic.id)}">${rkEscapeHtml(topic.name)}</option>`
    ).join("");
    topicSelect.value = selectedTopicId && matchingTopics.some(topic => Number(topic.id) === Number(selectedTopicId))
        ? String(selectedTopicId)
        : "all";
}

async function rkRefreshQuizAvailability() {
    const subjectId = Number(document.getElementById("quiz-subject").value);
    const topicValue = document.getElementById("quiz-topic").value;
    const difficulty = document.getElementById("quiz-difficulty").value || "Mixed";
    const requestedCount = Number(document.getElementById("quiz-question-count").value || 10);
    const note = document.getElementById("quiz-available-count");
    if (!subjectId || !note) return;
    try {
        const query = new URLSearchParams({ subject_id: subjectId, difficulty });
        if (topicValue !== "all") query.set("topic_id", topicValue);
        const response = await fetch(`/api/quiz/configuration?${query}`);
        if (!response.ok) throw new Error("Failed to load quiz configuration");
        const configuration = await response.json();
        const available = Number(configuration.available_questions || 0);
        note.textContent = available === 0
            ? "No questions are available for these filters yet."
            : `${available} question${available === 1 ? "" : "s"} available${available < requestedCount ? `; this quiz will use all ${available}.` : "."}`;
    } catch (error) {
        console.error("RK OS: Failed to check quiz question availability:", error);
        note.textContent = "Unable to check available questions.";
    }
}

function rkQuizSubjectChanged() {
    const subjectId = Number(document.getElementById("quiz-subject").value);
    rkQuizPopulateTopics(subjectId, null);
    rkRefreshQuizAvailability();
}

async function rkOpenQuizStudio(subjectId, topicId) {
    const subjectSelect = document.getElementById("quiz-subject");
    subjectSelect.innerHTML = rkStudyCatalog.subjects.map(subject =>
        `<option value="${Number(subject.id)}">${rkEscapeHtml(subject.name)}</option>`
    ).join("");
    subjectSelect.value = String(subjectId);
    rkQuizPopulateTopics(subjectId, topicId);
    document.getElementById("quiz-difficulty").value = "Mixed";
    document.getElementById("quiz-question-count").value = "10";
    document.getElementById("quiz-setup").hidden = false;
    document.getElementById("quiz-session-view").hidden = true;
    document.getElementById("quiz-dialog").showModal();
    await Promise.all([rkRefreshQuizAvailability(), rkLoadQuizHistory()]);
}

async function rkLoadQuizHistory() {
    const historyList = document.getElementById("quiz-history-list");
    if (!historyList) return;
    try {
        const [historyResponse, statsResponse] = await Promise.all([
            fetch("/api/quiz/history?limit=5"),
            fetch("/api/quiz/statistics")
        ]);
        if (!historyResponse.ok || !statsResponse.ok) throw new Error("Failed to load quiz history");
        const [history, stats] = await Promise.all([historyResponse.json(), statsResponse.json()]);
        const summary = document.getElementById("quiz-performance-summary");
        if (summary) {
            summary.innerHTML = `
                <div><span>Attempts</span><strong>${Number(stats.attempts || 0)}</strong></div>
                <div><span>Questions</span><strong>${Number(stats.questions || 0)}</strong></div>
                <div><span>Accuracy</span><strong>${Number(stats.accuracy || 0)}%</strong></div>
                <div><span>Best</span><strong>${Number(stats.best_accuracy || 0)}%</strong></div>
            `;
        }
        historyList.innerHTML = history.map(item => `
            <div class="quiz-history-row">
                <div><strong>${rkEscapeHtml(item.topic_name || "All Topics")}</strong><span>${rkEscapeHtml(item.subject_name)} · ${rkEscapeHtml(item.difficulty)}</span></div>
                <span>${Number(item.correct_answers)}/${Number(item.total_questions)} · ${Number(item.accuracy)}%</span>
                <time>${rkEscapeHtml(rkFormatRevisionDate(item.completed_at))}</time>
            </div>
        `).join("") || '<p class="study-empty-state">No completed quizzes yet.</p>';
    } catch (error) {
        console.error("RK OS: Failed to load quiz history:", error);
        historyList.innerHTML = '<p class="study-empty-state">Unable to load quiz history.</p>';
    }
}

async function rkStartQuiz() {
    const subjectId = Number(document.getElementById("quiz-subject").value);
    const topicValue = document.getElementById("quiz-topic").value;
    const difficulty = document.getElementById("quiz-difficulty").value || "Mixed";
    const requestedCount = Number(document.getElementById("quiz-question-count").value || 10);
    const startButton = document.querySelector(".quiz-start-button");
    const status = document.getElementById("quiz-available-count");
    if (startButton) startButton.disabled = true;
    try {
        const response = await fetch("/api/quiz/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                subject_id: subjectId,
                topic_id: topicValue === "all" ? null : Number(topicValue),
                difficulty,
                total_questions: requestedCount
            })
        });
        const session = await response.json();
        if (!response.ok) {
            if (status) status.textContent = session.detail || "Unable to start this quiz.";
            return;
        }
        rkQuizState.session = session;
        rkQuizState.index = 0;
        rkQuizState.results = [];
        rkQuizState.requestedCount = requestedCount;
        rkQuizState.filters = { subjectId, topicId: topicValue, difficulty };
        document.getElementById("quiz-setup").hidden = true;
        document.getElementById("quiz-session-view").hidden = false;
        rkRenderQuizQuestion();
    } catch (error) {
        console.error("RK OS: Failed to start quiz:", error);
        if (status) status.textContent = "Unable to start this quiz.";
    } finally {
        if (startButton) startButton.disabled = false;
    }
}

function rkRenderQuizQuestion() {
    const question = rkQuizState.session.questions[rkQuizState.index];
    const view = document.getElementById("quiz-session-view");
    const options = ["A", "B", "C", "D"].map(option => `
        <label class="practice-option" for="quiz-option-${option}">
            <input id="quiz-option-${option}" type="radio" name="quiz-answer" value="${option}">
            <span class="practice-option-letter">${option}</span>
            <span>${rkEscapeHtml(question[`option_${option.toLowerCase()}`])}</span>
        </label>
    `).join("");
    view.innerHTML = `
        <div class="practice-question-meta"><span>Question ${rkQuizState.index + 1} / ${rkQuizState.session.total_questions}</span><span>${rkEscapeHtml(question.difficulty)}</span></div>
        <p class="practice-question-subject">${rkEscapeHtml(rkQuizState.session.subject_name)} / ${rkEscapeHtml(rkQuizState.session.topic_name)}</p>
        <h4 class="practice-question-text">${rkEscapeHtml(question.question_text)}</h4>
        <div class="practice-options">${options}</div>
        <p class="practice-source">${rkEscapeHtml(question.source)}</p>
        <p id="quiz-answer-error" class="practice-answer-error" role="alert"></p>
        <button class="primary-button quiz-submit-button" type="button" onclick="rkSubmitQuizAnswer()">Submit Answer</button>
    `;
}

async function rkSubmitQuizAnswer() {
    const question = rkQuizState.session.questions[rkQuizState.index];
    const selected = document.querySelector('input[name="quiz-answer"]:checked');
    const error = document.getElementById("quiz-answer-error");
    const submit = document.querySelector(".quiz-submit-button");
    if (!selected) {
        if (error) error.textContent = "Select an answer before submitting.";
        return;
    }
    if (submit) submit.disabled = true;
    try {
        const response = await fetch(`/api/quiz/sessions/${rkQuizState.session.id}/answers`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question_id: question.id, selected_option: selected.value })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Unable to save this answer.");
        rkQuizState.results.push(result);
        rkRenderQuizAnswer(question, result);
    } catch (requestError) {
        console.error("RK OS: Failed to save quiz answer:", requestError);
        if (error) error.textContent = requestError.message || "Unable to save this answer.";
        if (submit) submit.disabled = false;
    }
}

function rkRenderQuizAnswer(question, result) {
    const correctText = question[`option_${result.correct_option.toLowerCase()}`];
    document.getElementById("quiz-session-view").innerHTML = `
        <div class="practice-question-meta"><span>Question ${rkQuizState.index + 1} / ${rkQuizState.session.total_questions}</span><span>${rkEscapeHtml(question.difficulty)}</span></div>
        <h4 class="practice-question-text">${rkEscapeHtml(question.question_text)}</h4>
        <div class="practice-result ${result.is_correct ? "correct" : "incorrect"}">
            <strong>${result.is_correct ? "Correct" : "Incorrect"}</strong>
            <p>Correct answer: ${rkEscapeHtml(result.correct_option)}. ${rkEscapeHtml(correctText)}</p>
            <p>${rkEscapeHtml(result.explanation)}</p>
        </div>
        <p class="practice-source">${rkEscapeHtml(question.source)}</p>
        <button class="primary-button quiz-next-button" type="button" onclick="rkNextQuizQuestion()">${rkQuizState.index + 1 === rkQuizState.session.total_questions ? "See Results" : "Next Question"}</button>
    `;
}

async function rkNextQuizQuestion() {
    rkQuizState.index += 1;
    if (rkQuizState.index < rkQuizState.session.total_questions) {
        rkRenderQuizQuestion();
        return;
    }
    try {
        const response = await fetch(`/api/quiz/sessions/${rkQuizState.session.id}/complete`, { method: "POST" });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || "Unable to complete quiz.");
        await rkRefreshRKOSData({ study: true });
        await rkLoadQuizHistory();
        rkRenderQuizResult(result);
    } catch (error) {
        console.error("RK OS: Failed to complete quiz:", error);
        const view = document.getElementById("quiz-session-view");
        view.insertAdjacentHTML("beforeend", `<p class="practice-answer-error">${rkEscapeHtml(error.message)}</p>`);
    }
}

function rkRenderQuizResult(result) {
    const minutes = Math.floor(Number(result.time_taken_seconds || 0) / 60);
    const seconds = Number(result.time_taken_seconds || 0) % 60;
    const timeTaken = minutes ? `${minutes}m ${seconds}s` : `${seconds}s`;
    document.getElementById("quiz-session-view").innerHTML = `
        <div class="practice-complete quiz-complete">
            <p class="eyebrow">QUIZ COMPLETE</p>
            <h4>Score ${Number(result.correct_answers)} / ${Number(result.total_questions)}</h4>
            <div class="practice-score-grid">
                <div><span>Correct</span><strong>${Number(result.correct_answers)}</strong></div>
                <div><span>Incorrect</span><strong>${Number(result.incorrect_answers)}</strong></div>
                <div><span>Accuracy</span><strong>${Number(result.accuracy)}%</strong></div>
                <div><span>Time Taken</span><strong>${rkEscapeHtml(timeTaken)}</strong></div>
            </div>
            <div class="practice-complete-actions">
                <button class="primary-button" type="button" onclick="rkRetryQuiz()">Retry Quiz</button>
                <button class="secondary-button" type="button" onclick="rkCloseQuizStudio()">Back to Learn</button>
            </div>
        </div>
    `;
}

async function rkRetryQuiz() {
    const filters = { ...rkQuizState.filters };
    document.getElementById("quiz-setup").hidden = false;
    document.getElementById("quiz-session-view").hidden = true;
    document.getElementById("quiz-subject").value = String(filters.subjectId);
    rkQuizPopulateTopics(filters.subjectId, filters.topicId === "all" ? null : filters.topicId);
    document.getElementById("quiz-difficulty").value = filters.difficulty;
    document.getElementById("quiz-question-count").value = String(rkQuizState.requestedCount);
    await rkStartQuiz();
}

function rkCloseQuizStudio() {
    document.getElementById("quiz-dialog").close();
    rkStudyStateQuizReset();
}

function rkStudyStateQuizReset() {
    rkQuizState.session = null;
    rkQuizState.index = 0;
    rkQuizState.results = [];
    rkLoadStudyPage();
}

function rkRevisionTopicCard(topic, showAccuracy, showReview) {
    const accuracy = showAccuracy
        ? `<span class="revision-accuracy">${Number(topic.accuracy || 0)}% accuracy · ${Number(topic.questions_attempted || 0)} attempts</span>`
        : `<span class="revision-accuracy">Last studied ${rkEscapeHtml(rkFormatRevisionDate(topic.last_studied))}</span>`;
    const reviewed = showReview
        ? `<button class="revision-reviewed-button" type="button" ${topic.reviewed_today ? "disabled" : ""} onclick="rkMarkRevisionReviewed(${Number(topic.topic_id)})">${topic.reviewed_today ? "Reviewed today" : "Mark Reviewed"}</button>`
        : "";
    return `
        <article class="revision-topic-card">
            <div class="revision-topic-heading">
                <strong>${rkEscapeHtml(topic.topic_name)}</strong>
                <span>${rkEscapeHtml(topic.subject_name)}</span>
            </div>
            ${accuracy}
            <div class="revision-topic-actions">
                <button class="revision-open-button" type="button" onclick="rkOpenRevisionTopic(${Number(topic.subject_id)}, ${Number(topic.topic_id)})">Revise Topic</button>
                ${reviewed}
            </div>
        </article>
    `;
}

function rkFormatRevisionDate(value) {
    if (!value) return "not recorded";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "not recorded" : parsed.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

async function rkOpenRevision() {
    const dialog = document.getElementById("revision-dialog");
    dialog.showModal();
    const content = document.getElementById("revision-content");
    content.innerHTML = '<p class="study-empty-state">Loading revision topics...</p>';
    try {
        const response = await fetch("/api/revision/topics");
        if (!response.ok) throw new Error("Failed to load revision topics");
        const data = await response.json();
        rkRenderRevision(data);
    } catch (error) {
        console.error("RK OS: Failed to load revision topics:", error);
        content.innerHTML = '<p class="study-empty-state">Unable to load revision topics.</p>';
    }
}

function rkRenderRevision(data) {
    const content = document.getElementById("revision-content");
    const recentTopics = data.recent_topics || [];
    const weakAreas = data.weak_areas || [];
    const recentlyStudied = data.recently_studied || [];
    content.innerHTML = `
        <div class="revision-today-count"><span>Today's Revision</span><strong>${Number(data.today_revision_count || 0)}</strong></div>
        <section class="revision-section"><h4>Recent Topics</h4><div class="revision-topic-list">${recentTopics.map(topic => rkRevisionTopicCard(topic, true, true)).join("") || '<p class="study-empty-state">No practice topics yet.</p>'}</div></section>
        <section class="revision-section"><h4>Weak Areas <span>Accuracy below 70%</span></h4><div class="revision-topic-list">${weakAreas.map(topic => rkRevisionTopicCard(topic, true, true)).join("") || '<p class="study-empty-state">No weak areas from practice attempts.</p>'}</div></section>
        <section class="revision-section"><h4>Recently Studied</h4><div class="revision-topic-list">${recentlyStudied.map(topic => rkRevisionTopicCard(topic, false, true)).join("") || '<p class="study-empty-state">No study sessions recorded yet.</p>'}</div></section>
    `;
}

async function rkMarkRevisionReviewed(topicId) {
    try {
        const response = await fetch("/api/revision/reviews", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ topic_id: Number(topicId) })
        });
        if (!response.ok) throw new Error("Failed to save revision review");
        await rkOpenRevision();
    } catch (error) {
        console.error("RK OS: Failed to mark topic reviewed:", error);
    }
}

async function rkOpenRevisionTopic(subjectId, topicId) {
    document.getElementById("revision-dialog").close();
    rkStudySelection.subjectId = Number(subjectId);
    rkStudySelection.topicId = Number(topicId);
    await rkLoadStudyPage();
    document.getElementById("study-detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function rkRefreshRKOSData({ tasks = false, habits = false, goals = false, study = false } = {}) {
    const refreshes = [
        loadDashboardData(),
        rkLoadProgress(),
        rkLoadSevenDayHistory()
    ];

    if (tasks) refreshes.push(rkLoadTasks());
    if (habits) refreshes.push(rkLoadHabits());
    if (goals) refreshes.push(rkLoadGoals());
    if (study) refreshes.push(rkLoadStudyPage());

    const results = await Promise.all(refreshes);
    await rkLoadConsistency(results[2]);
}

window.rkStudyStartTimer = rkStudyStartTimer;
window.rkStudyPauseTimer = rkStudyPauseTimer;
window.rkStudyEndSession = rkStudyEndSession;
window.rkOpenStudyNote = rkOpenStudyNote;
window.rkNavigateToSection = rkNavigateToSection;
window.rkSetFocusPreset = rkSetFocusPreset;
window.rkStartFocusTimer = rkStartFocusTimer;
window.rkResetFocusTimer = rkResetFocusTimer;
window.rkSaveProfile = rkSaveProfile;
window.rkSendAssistantMessage = rkSendAssistantMessage;
window.rkAssistantQuickAction = rkAssistantQuickAction;
window.rkOpenStudyLibrary = rkOpenStudyLibrary;
window.rkOpenPracticeCurrent = rkOpenPracticeCurrent;
window.rkOpenQuizCurrent = rkOpenQuizCurrent;
window.rkOpenPractice = rkOpenPractice;
window.rkPracticeSubjectChanged = rkPracticeSubjectChanged;
window.rkLoadPracticeQuestionsFromFilters = rkLoadPracticeQuestionsFromFilters;
window.rkSubmitPracticeAnswer = rkSubmitPracticeAnswer;
window.rkPracticeNextQuestion = rkPracticeNextQuestion;
window.rkClosePracticeToTopic = rkClosePracticeToTopic;
window.rkOpenQuizStudio = rkOpenQuizStudio;
window.rkQuizSubjectChanged = rkQuizSubjectChanged;
window.rkRefreshQuizAvailability = rkRefreshQuizAvailability;
window.rkStartQuiz = rkStartQuiz;
window.rkSubmitQuizAnswer = rkSubmitQuizAnswer;
window.rkNextQuizQuestion = rkNextQuizQuestion;
window.rkRetryQuiz = rkRetryQuiz;
window.rkCloseQuizStudio = rkCloseQuizStudio;
window.rkOpenRevision = rkOpenRevision;
window.rkOpenRevisionTopic = rkOpenRevisionTopic;
window.rkMarkRevisionReviewed = rkMarkRevisionReviewed;
window.rkSelectStudySubject = function(subjectId) {
    rkStudySelection.subjectId = Number(subjectId);
    rkStudySelection.topicId = null;
    rkLoadStudyPage();
};
window.rkSelectStudyTopic = function(subjectId, topicId) {
    rkStudySelection.subjectId = Number(subjectId);
    rkStudySelection.topicId = Number(topicId);
    rkLoadStudyPage();
};

window.rkStudyRestoreTimerState = rkStudyRestoreTimerState;
window.rkLoadStudyPage = rkLoadStudyPage;


/* =========================================================
   RK OS — TASKS MODULE
   13Q–13T
   ========================================================= */

async function rkLoadTasks() {
    const tasksList = document.getElementById("tasks-list");
    const activeCount = document.getElementById("active-task-count");

    if (!tasksList) {
        return;
    }

    try {
        const response = await fetch("/api/tasks");

        if (!response.ok) {
            throw new Error("Failed to load tasks");
        }

        const tasks = await response.json();

        renderRKTasks(tasks);

    } catch (error) {
        console.error("RK OS: Failed to load tasks:", error);

        tasksList.innerHTML = `
            <div class="task-empty-state">
                <div class="empty-icon">!</div>
                <h4>Unable to load tasks</h4>
                <p>Please make sure the RK OS backend is running.</p>
            </div>
        `;

        if (activeCount) {
            activeCount.textContent = "Unavailable";
        }
    }
}


function renderRKTasks(tasks) {
    const tasksList = document.getElementById("tasks-list");
    const activeCount = document.getElementById("active-task-count");

    if (!tasksList) {
        return;
    }

    const activeTasks = tasks.filter(
        task => Number(task.completed) === 0
    );

    if (activeCount) {
        activeCount.textContent =
            `${activeTasks.length} active`;
    }

    if (!tasks.length) {
        tasksList.innerHTML = `
            <div class="task-empty-state">
                <div class="empty-icon">✓</div>
                <h4>No tasks yet</h4>
                <p>Your tasks will appear here.</p>
            </div>
        `;

        return;
    }

    tasksList.innerHTML = tasks.map(task => {
        const completed = Number(task.completed) === 1;

        return `
            <div
                class="rk-task-card ${completed ? "completed" : ""}"
                data-task-id="${task.id}"
            >
                <label class="rk-task-main">

                    <input
                        class="rk-task-checkbox"
                        type="checkbox"
                        ${completed ? "checked" : ""}
                        onchange="rkToggleTask(${task.id}, this.checked)"
                    >

                    <span class="rk-task-title">
                        ${rkEscapeHtml(task.title)}
                    </span>

                </label>

                <button
                    class="rk-task-delete"
                    type="button"
                    onclick="rkDeleteTask(${task.id})"
                    aria-label="Delete task"
                >
                    Delete
                </button>
            </div>
        `;
    }).join("");
}


function rkEscapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


async function rkAddTask() {
    const input = document.getElementById("task-title");

    if (!input) {
        return;
    }

    const title = input.value.trim();

    if (!title) {
        input.focus();
        return;
    }

    try {
        const response = await fetch("/api/tasks", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                title: title
            })
        });

        if (!response.ok) {
            throw new Error("Failed to create task");
        }

        input.value = "";

        await rkRefreshRKOSData({ tasks: true });

        input.focus();

    } catch (error) {
        console.error("RK OS: Failed to add task:", error);
        alert("Unable to add task. Please try again.");
    }
}


async function rkToggleTask(taskId, completed) {
    try {
        const response = await fetch(
            `/api/tasks/${taskId}`,
            {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    completed: completed
                })
            }
        );

        if (!response.ok) {
            throw new Error("Failed to update task");
        }

        await rkRefreshRKOSData({ tasks: true });

    } catch (error) {
        console.error(
            "RK OS: Failed to update task:",
            error
        );

        await rkLoadTasks();

        alert("Unable to update task. Please try again.");
    }
}


async function rkDeleteTask(taskId) {
    const confirmed = confirm(
        "Delete this task?"
    );

    if (!confirmed) {
        return;
    }

    try {
        const response = await fetch(
            `/api/tasks/${taskId}`,
            {
                method: "DELETE"
            }
        );

        if (!response.ok) {
            throw new Error("Failed to delete task");
        }

        await rkRefreshRKOSData({ tasks: true });

    } catch (error) {
        console.error(
            "RK OS: Failed to delete task:",
            error
        );

        alert("Unable to delete task. Please try again.");
    }
}


/* ============================================================
   RK OS - GOALS MODULE
   ============================================================ */

async function rkLoadGoals() {

    const goalsList = document.getElementById("goals-list");
    const activeCount = document.getElementById("active-goal-count");

    if (!goalsList) return;

    try {

        const response = await fetch("/api/goals");

        if (!response.ok) {
            throw new Error("Failed to load goals");
        }

        const goals = await response.json();

        rkRenderGoals(goals);

    } catch (error) {

        console.error("RK OS: Failed to load goals:", error);

        goalsList.innerHTML = `
            <div class="goal-empty-state">
                <div class="goal-empty-icon">!</div>
                <h4>Unable to load goals</h4>
                <p>Please make sure the RK OS backend is running.</p>
            </div>
        `;

        if (activeCount) {
            activeCount.textContent = "Unavailable";
        }
    }
}


function rkRenderGoals(goals) {

    const goalsList = document.getElementById("goals-list");
    const activeCount = document.getElementById("active-goal-count");

    if (!goalsList) return;

    if (activeCount) {
        activeCount.textContent = `${goals.length} active`;
    }

    if (!goals.length) {

        goalsList.innerHTML = `
            <div class="goal-empty-state">

                <div class="goal-empty-icon">
                    ◎
                </div>

                <h4>No goals yet</h4>

                <p>
                    Add a goal and start moving toward it.
                </p>

            </div>
        `;

        return;
    }


    goalsList.innerHTML = goals.map(goal => {

        const progress = Math.max(
            0,
            Math.min(
                100,
                Number(goal.progress) || 0
            )
        );

        const targetDate = goal.target_date
            ? new Date(goal.target_date + "T00:00:00")
                .toLocaleDateString(
                    undefined,
                    {
                        day: "2-digit",
                        month: "short",
                        year: "numeric"
                    }
                )
            : "No target date";

        return `
            <div
                class="rk-goal-card"
                data-goal-id="${goal.id}"
            >

                <div class="rk-goal-top">

                    <div>

                        <h4 class="rk-goal-title">
                            ${rkGoalEscapeHtml(goal.title)}
                        </h4>

                        <div class="rk-goal-date">
                            Target: ${targetDate}
                        </div>

                    </div>

                    <div class="rk-goal-actions">

                        <button
                            class="rk-goal-action"
                            type="button"
                            onclick="rkEditGoal(${goal.id})"
                        >
                            Edit
                        </button>

                        <button
                            class="rk-goal-action delete"
                            type="button"
                            onclick="rkDeleteGoal(${goal.id})"
                        >
                            Delete
                        </button>

                    </div>

                </div>


                <div class="rk-goal-progress-row">

                    <input
                        class="rk-goal-progress"
                        type="range"
                        min="0"
                        max="100"
                        value="${progress}"
                        onchange="rkUpdateGoalProgress(${goal.id}, this.value)"
                    >

                    <span class="rk-goal-progress-value">
                        ${progress}%
                    </span>

                </div>

            </div>
        `;

    }).join("");
}


function rkGoalEscapeHtml(value) {

    return String(value)

        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


async function rkAddGoal() {

    const titleInput =
        document.getElementById("goal-title");

    const dateInput =
        document.getElementById("goal-target-date");

    if (!titleInput) return;

    const title =
        titleInput.value.trim();

    const targetDate =
        dateInput ? dateInput.value : null;


    if (!title) {

        titleInput.focus();

        return;
    }


    try {

        const response = await fetch(
            "/api/goals",
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    title: title,
                    target_date: targetDate || null,
                    progress: 0
                })
            }
        );


        if (!response.ok) {
            throw new Error("Failed to create goal");
        }


        titleInput.value = "";

        if (dateInput) {
            dateInput.value = "";
        }

        await rkRefreshRKOSData({ goals: true });


        titleInput.focus();


    } catch (error) {

        console.error(
            "RK OS: Failed to add goal:",
            error
        );

        alert(
            "Unable to add goal. Please try again."
        );
    }
}


async function rkUpdateGoalProgress(
    goalId,
    progress
) {

    try {

        const response = await fetch(
            `/api/goals/${goalId}`,
            {
                method: "PUT",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    progress: Number(progress)
                })
            }
        );


        if (!response.ok) {
            throw new Error(
                "Failed to update goal progress"
            );
        }


        await rkRefreshRKOSData({ goals: true });


    } catch (error) {

        console.error(
            "RK OS: Failed to update goal:",
            error
        );

        alert(
            "Unable to update goal. Please try again."
        );

        await rkRefreshRKOSData({ goals: true });
    }
}


async function rkEditGoal(goalId) {

    try {

        const response =
            await fetch("/api/goals");

        if (!response.ok) {
            throw new Error(
                "Failed to load goals"
            );
        }


        const goals =
            await response.json();


        const goal =
            goals.find(
                item =>
                    Number(item.id) ===
                    Number(goalId)
            );


        if (!goal) {
            return;
        }


        const newTitle =
            prompt(
                "Goal name:",
                goal.title
            );


        if (newTitle === null) {
            return;
        }


        const cleanTitle =
            newTitle.trim();


        if (!cleanTitle) {
            return;
        }


        const newDate =
            prompt(
                "Target date (YYYY-MM-DD):",
                goal.target_date || ""
            );


        if (newDate === null) {
            return;
        }


        const responseUpdate =
            await fetch(
                `/api/goals/${goalId}`,
                {
                    method: "PUT",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        title: cleanTitle,
                        target_date:
                            newDate || null,
                        progress:
                            Number(goal.progress) || 0
                    })
                }
            );


        if (!responseUpdate.ok) {
            throw new Error(
                "Failed to edit goal"
            );
        }


        await rkLoadGoals();


    } catch (error) {

        console.error(
            "RK OS: Failed to edit goal:",
            error
        );

        alert(
            "Unable to edit goal. Please try again."
        );
    }
}


async function rkDeleteGoal(goalId) {

    const confirmed =
        confirm(
            "Delete this goal?"
        );


    if (!confirmed) {
        return;
    }


    try {

        const response =
            await fetch(
                `/api/goals/${goalId}`,
                {
                    method: "DELETE"
                }
            );


        if (!response.ok) {
            throw new Error(
                "Failed to delete goal"
            );
        }


        await rkRefreshRKOSData({ goals: true });


    } catch (error) {

        console.error(
            "RK OS: Failed to delete goal:",
            error
        );

        alert(
            "Unable to delete goal. Please try again."
        );
    }
}


/* Press Enter to add a goal */

document.addEventListener(
    "keydown",
    event => {

        const input =
            document.getElementById(
                "goal-title"
            );


        if (
            input &&
            document.activeElement === input &&
            event.key === "Enter"
        ) {

            event.preventDefault();

            rkAddGoal();
        }

    }
);


/* ============================================================
   RK OS - PROGRESS / ANALYTICS MODULE
   ============================================================ */

async function rkLoadProgress() {

    try {

        const response =
            await fetch("/api/progress");

        if (!response.ok) {
            throw new Error(
                "Failed to load progress"
            );
        }

        const data =
            await response.json();

        rkRenderProgress(data);

    } catch (error) {

        console.error(
            "RK OS: Failed to load progress:",
            error
        );

    }
}


function rkRenderProgress(data) {

    const overall =
        Number(data.overall_score) || 0;

    const tasks =
        data.tasks || {};

    const habits =
        data.habits || {};

    const goals =
        data.goals || {};
    const study = data.study || {};


    /* Overall */

    const overallScore =
        document.getElementById(
            "overall-score"
        );

    const overallBar =
        document.getElementById(
            "overall-progress-bar"
        );


    if (overallScore) {
        overallScore.textContent =
            overall;
    }

    if (overallBar) {
        overallBar.style.width =
            `${overall}%`;
    }


    /* Tasks */

    const taskPercent =
        Number(tasks.completion) || 0;

    const taskPercentElement =
        document.getElementById(
            "progress-task-percent"
        );

    const taskSummary =
        document.getElementById(
            "progress-task-summary"
        );

    const taskBar =
        document.getElementById(
            "progress-task-bar"
        );


    if (taskPercentElement) {
        taskPercentElement.textContent =
            `${taskPercent}%`;
    }

    if (taskSummary) {
        taskSummary.textContent =
            `${tasks.completed || 0} of ${tasks.total || 0} completed`;
    }

    if (taskBar) {
        taskBar.style.width =
            `${taskPercent}%`;
    }


    /* Habits */

    const habitPercent =
        Number(habits.completion) || 0;

    const habitPercentElement =
        document.getElementById(
            "progress-habit-percent"
        );

    const habitSummary =
        document.getElementById(
            "progress-habit-summary"
        );

    const habitBar =
        document.getElementById(
            "progress-habit-bar"
        );


    if (habitPercentElement) {
        habitPercentElement.textContent =
            `${habitPercent}%`;
    }

    if (habitSummary) {
        habitSummary.textContent =
            `${habits.completed || 0} of ${habits.total || 0} completed`;
    }

    if (habitBar) {
        habitBar.style.width =
            `${habitPercent}%`;
    }


    /* Goals */

    const goalPercent =
        Number(goals.progress) || 0;

    const goalPercentElement =
        document.getElementById(
            "progress-goal-percent"
        );

    const goalSummary =
        document.getElementById(
            "progress-goal-summary"
        );

    const goalBar =
        document.getElementById(
            "progress-goal-bar"
        );


    if (goalPercentElement) {
        goalPercentElement.textContent =
            `${goalPercent}%`;
    }

    if (goalSummary) {

        const count =
            Number(goals.total) || 0;

        goalSummary.textContent =
            `${count} goal${count === 1 ? "" : "s"} tracked`;
    }

    if (goalBar) {
        goalBar.style.width =
            `${goalPercent}%`;
    }

    const studyTime = document.getElementById("progress-study-time");
    const studySessions = document.getElementById("progress-study-sessions");
    const studyTopics = document.getElementById("progress-study-topics");
    if (studyTime) studyTime.textContent = rkFormatStudyMinutes(Number(study.study_minutes || 0));
    if (studySessions) studySessions.textContent = Number(study.sessions || 0);
    if (studyTopics) studyTopics.textContent = Number(study.topics_studied || 0);

    const practice = data.practice || {};
    const practiceQuestions = document.getElementById("progress-practice-questions");
    const practiceCorrect = document.getElementById("progress-practice-correct");
    const practiceAccuracy = document.getElementById("progress-practice-accuracy");
    const practiceWeakTopics = document.getElementById("progress-practice-weak-topics");
    if (practiceQuestions) practiceQuestions.textContent = Number(practice.questions || 0);
    if (practiceCorrect) practiceCorrect.textContent = Number(practice.correct || 0);
    if (practiceAccuracy) practiceAccuracy.textContent = `${Number(practice.accuracy || 0)}%`;
    if (practiceWeakTopics) practiceWeakTopics.textContent = Number(practice.weak_topics || 0);

    const quiz = data.quiz || {};
    const quizAttempts = document.getElementById("progress-quiz-attempts");
    const quizQuestions = document.getElementById("progress-quiz-questions");
    const quizAccuracy = document.getElementById("progress-quiz-accuracy");
    const quizBest = document.getElementById("progress-quiz-best");
    if (quizAttempts) quizAttempts.textContent = Number(quiz.attempts || 0);
    if (quizQuestions) quizQuestions.textContent = Number(quiz.questions || 0);
    if (quizAccuracy) quizAccuracy.textContent = `${Number(quiz.accuracy || 0)}%`;
    if (quizBest) quizBest.textContent = `${Number(quiz.best_accuracy || 0)}%`;


    /* Total items */

    const totalItems =
        Number(data.total_items) || 0;

    const totalItemsElement =
        document.getElementById(
            "progress-total-items"
        );

    if (totalItemsElement) {

        totalItemsElement.textContent =
            `${totalItems} item${totalItems === 1 ? "" : "s"} tracked`;
    }

}


// ============================================================
// RK OS - DASHBOARD ACTIVITY SNAPSHOT
// ============================================================

async function rkCreateDashboardSnapshot() {
    try {
        const response = await fetch("/api/activity-history/snapshot", {
            method: "POST"
        });

        if (!response.ok) {
            throw new Error("Snapshot request failed");
        }

        const snapshot = await response.json();

        console.log(
            "RK OS: Daily activity snapshot saved:",
            snapshot
        );

    } catch (error) {
        console.error(
            "RK OS: Failed to create daily snapshot:",
            error
        );
    }
}


// ============================================================
// RK OS - 7 DAY ACTIVITY HISTORY
// ============================================================

async function rkLoadSevenDayHistory() {
    const progressSection = document.getElementById("progress");

    if (!progressSection) {
        return;
    }

    try {
        const response = await fetch("/api/activity-history?limit=7");

        if (!response.ok) {
            throw new Error("Failed to load activity history");
        }

        const history = await response.json();

        rkRenderSevenDayHistory(history);
        return history;

    } catch (error) {

        console.error(
            "RK OS: Failed to load 7-day history:",
            error
        );

        rkRenderSevenDayHistory([]);
        return [];
    }
}


function rkRenderSevenDayHistory(history) {

    const progressSection = document.getElementById("progress");

    if (!progressSection) {
        return;
    }

    let historyCard = document.getElementById(
        "rk-seven-day-history"
    );

    if (!historyCard) {

        historyCard = document.createElement("div");

        historyCard.id = "rk-seven-day-history";

        historyCard.className =
            "rk-seven-day-history";

        progressSection.appendChild(historyCard);
    }


    if (!history.length) {

        historyCard.innerHTML = `
            <div class="rk-history-header">
                <div>
                    <span class="rk-history-label">
                        ACTIVITY
                    </span>

                    <h3>Last 7 Days</h3>

                    <p>
                        Your daily activity history will appear here.
                    </p>
                </div>
            </div>

            <div class="rk-history-empty">
                <div class="rk-history-empty-icon">◷</div>

                <h4>No history yet</h4>

                <p>
                    Use RK OS and your daily activity will be recorded automatically.
                </p>
            </div>
        `;

        return;
    }


    historyCard.innerHTML = `
        <div class="rk-history-header">

            <div>
                <span class="rk-history-label">
                    ACTIVITY
                </span>

                <h3>Last 7 Days</h3>

                <p>
                    Your recent productivity history.
                </p>
            </div>

            <span class="rk-history-count">
                ${history.length} day${history.length === 1 ? "" : "s"}
            </span>

        </div>

        <div class="rk-history-list">

            ${history.map(day => {

                const date = new Date(
                    `${day.activity_date}T00:00:00`
                );

                const formattedDate =
                    date.toLocaleDateString(
                        "en-IN",
                        {
                            day: "2-digit",
                            month: "short"
                        }
                    );

                return `
                    <div class="rk-history-row">

                        <div class="rk-history-date">
                            <strong>
                                ${formattedDate}
                            </strong>

                            <span>
                                ${day.activity_date}
                            </span>
                        </div>


                        <div class="rk-history-stat">
                            <span>Tasks</span>

                            <strong>
                                ${day.tasks_completed}/${day.tasks_total}
                            </strong>
                        </div>


                        <div class="rk-history-stat">
                            <span>Habits</span>

                            <strong>
                                ${day.habits_completed}/${day.habits_total}
                            </strong>
                        </div>


                        <div class="rk-history-stat">
                            <span>Goal</span>

                            <strong>
                                ${day.goal_progress}%
                            </strong>
                        </div>


                        <div class="rk-history-score">
                            <span>Score</span>

                            <strong>
                                ${day.overall_score}
                            </strong>
                        </div>

                    </div>
                `;

            }).join("")}

        </div>
    `;
}


// ============================================================
// RK OS - STREAKS & CONSISTENCY
// ============================================================

function rkCalculateConsistency(history) {

    if (!Array.isArray(history) || history.length === 0) {
        return {
            currentStreak: 0,
            activeDays: 0,
            averageScore: 0,
            consistency: 0
        };
    }

    // --------------------------------------------------------
    // Normalize and sort dates newest -> oldest
    // --------------------------------------------------------

    const normalizedHistory = history
        .filter(day => day && day.activity_date)
        .map(day => ({
            ...day,
            dateObject: new Date(
                `${day.activity_date}T00:00:00`
            )
        }))
        .filter(day => !Number.isNaN(day.dateObject.getTime()))
        .sort(
            (a, b) =>
                b.dateObject.getTime() -
                a.dateObject.getTime()
        );


    if (!normalizedHistory.length) {
        return {
            currentStreak: 0,
            activeDays: 0,
            averageScore: 0,
            consistency: 0
        };
    }


    // --------------------------------------------------------
    // Active days
    // --------------------------------------------------------

    const activeDays = normalizedHistory.length;


    // --------------------------------------------------------
    // Average score
    // --------------------------------------------------------

    const totalScore = normalizedHistory.reduce(
        (sum, day) =>
            sum + Number(day.overall_score || 0),
        0
    );

    const averageScore = Math.round(
        totalScore / activeDays
    );


    // --------------------------------------------------------
    // Current streak
    //
    // A streak counts consecutive calendar days
    // from the newest recorded day.
    // --------------------------------------------------------

    let currentStreak = 1;

    for (
        let i = 1;
        i < normalizedHistory.length;
        i++
    ) {

        const previousDate =
            normalizedHistory[i - 1].dateObject;

        const currentDate =
            normalizedHistory[i].dateObject;

        const difference =
            Math.round(
                (
                    previousDate.getTime() -
                    currentDate.getTime()
                ) /
                (1000 * 60 * 60 * 24)
            );


        if (difference === 1) {
            currentStreak++;
        } else {
            break;
        }
    }


    // --------------------------------------------------------
    // 7-day consistency
    //
    // One active day out of seven = 14%.
    // Seven active days out of seven = 100%.
    // --------------------------------------------------------

    const consistency = Math.round(
        Math.min(activeDays, 7) / 7 * 100
    );


    return {
        currentStreak,
        activeDays,
        averageScore,
        consistency
    };
}


function rkRenderConsistency(history) {

    const progressSection =
        document.getElementById("progress");

    if (!progressSection) {
        return;
    }


    let consistencyCard =
        document.getElementById(
            "rk-consistency-card"
        );


    if (!consistencyCard) {

        consistencyCard =
            document.createElement("div");

        consistencyCard.id =
            "rk-consistency-card";

        consistencyCard.className =
            "rk-consistency-card";


        // Put consistency BEFORE activity history
        const historyCard =
            document.getElementById(
                "rk-seven-day-history"
            );


        if (historyCard) {

            progressSection.insertBefore(
                consistencyCard,
                historyCard
            );

        } else {

            progressSection.appendChild(
                consistencyCard
            );
        }
    }


    const stats =
        rkCalculateConsistency(history);


    consistencyCard.innerHTML = `

        <div class="rk-consistency-header">

            <div>

                <span class="rk-consistency-label">
                    CONSISTENCY
                </span>

                <h3>
                    Streaks & Consistency
                </h3>

                <p>
                    Your recent discipline and activity.
                </p>

            </div>

        </div>


        <div class="rk-consistency-stats">


            <div class="rk-consistency-stat">

                <div class="rk-consistency-icon">
                    🔥
                </div>

                <div>

                    <span>
                        Current streak
                    </span>

                    <strong>
                        ${stats.currentStreak}
                        ${stats.currentStreak === 1 ? "day" : "days"}
                    </strong>

                </div>

            </div>


            <div class="rk-consistency-stat">

                <div class="rk-consistency-icon">
                    📅
                </div>

                <div>

                    <span>
                        Active days
                    </span>

                    <strong>
                        ${stats.activeDays}
                    </strong>

                </div>

            </div>


            <div class="rk-consistency-stat">

                <div class="rk-consistency-icon">
                    📈
                </div>

                <div>

                    <span>
                        Avg score
                    </span>

                    <strong>
                        ${stats.averageScore}
                    </strong>

                </div>

            </div>


        </div>


        <div class="rk-consistency-progress">

            <div class="rk-consistency-progress-top">

                <span>
                    7-day consistency
                </span>

                <strong>
                    ${stats.consistency}%
                </strong>

            </div>


            <div class="rk-consistency-track">

                <div
                    class="rk-consistency-fill"
                    style="width: ${stats.consistency}%"
                ></div>

            </div>


            <p>
                Active days recorded in the last 7-day window.
            </p>

        </div>

    `;
}


// ------------------------------------------------------------
// Load consistency after activity history
// ------------------------------------------------------------

async function rkLoadConsistency(history = null) {

    try {
        let historyData = history;

        if (!Array.isArray(historyData)) {
            const response = await fetch("/api/activity-history?limit=7");

            if (!response.ok) {
                throw new Error("Failed to load activity history");
            }

            historyData = await response.json();
        }


        rkRenderConsistency(historyData);

    } catch (error) {

        console.error(
            "RK OS: Failed to load consistency:",
            error
        );

        rkRenderConsistency([]);

    }
}


/* ============================================================
   RK OS - HABITS MODULE
   ============================================================ */

async function rkLoadHabits() {
    const habitsList = document.getElementById("habits-list");

    if (!habitsList) return;

    try {
        const response = await fetch("/api/habits");

        if (!response.ok) {
            throw new Error("Failed to load habits");
        }

        const habits = await response.json();

        rkRenderHabits(habits);

    } catch (error) {

        console.error("RK OS: Failed to load habits:", error);

        habitsList.innerHTML = `
            <div class="habit-empty-state">
                <div class="empty-icon">!</div>
                <h4>Unable to load habits</h4>
                <p>Please make sure the RK OS backend is running.</p>
            </div>
        `;
    }
}


function rkRenderHabits(habits) {

    const habitsList = document.getElementById("habits-list");
    const activeCount = document.getElementById("active-habit-count");

    if (!habitsList) return;

    const activeHabits = habits.filter(
        habit => Number(habit.completed) === 0
    );

    if (activeCount) {
        activeCount.textContent =
            `${activeHabits.length} active`;
    }


    if (!habits.length) {

        habitsList.innerHTML = `
            <div class="habit-empty-state">
                <div class="empty-icon">◆</div>
                <h4>No habits yet</h4>
                <p>Add a habit you want to complete every day.</p>
            </div>
        `;

        return;
    }


    habitsList.innerHTML = habits.map(habit => {

        const completed =
            Number(habit.completed) === 1;

        return `
            <div
                class="rk-habit-card ${completed ? "completed" : ""}"
                data-habit-id="${habit.id}"
            >

                <label class="rk-habit-main">

                    <input
                        class="rk-habit-checkbox"
                        type="checkbox"
                        ${completed ? "checked" : ""}
                        onchange="
                            rkToggleHabit(
                                ${habit.id},
                                this.checked
                            )
                        "
                    >

                    <span class="rk-habit-name">
                        ${rkEscapeHabitHtml(habit.name)}
                    </span>

                </label>

                <button
                    class="rk-habit-delete"
                    type="button"
                    onclick="rkDeleteHabit(${habit.id})"
                    aria-label="Delete habit"
                >
                    Delete
                </button>

            </div>
        `;

    }).join("");
}


function rkEscapeHabitHtml(value) {

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


async function rkAddHabit() {

    const input =
        document.getElementById("habit-name");

    if (!input) return;

    const name = input.value.trim();

    if (!name) {
        input.focus();
        return;
    }


    try {

        const response = await fetch("/api/habits", {
            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                name: name
            })
        });


        if (!response.ok) {
            throw new Error("Failed to create habit");
        }


        input.value = "";

        await rkRefreshRKOSData({ habits: true });

        input.focus();

    } catch (error) {

        console.error(
            "RK OS: Failed to add habit:",
            error
        );

        alert(
            "Unable to add habit. Please try again."
        );
    }
}


async function rkToggleHabit(
    habitId,
    completed
) {

    try {

        const response = await fetch(
            `/api/habits/${habitId}`,
            {
                method: "PUT",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    completed: completed
                })
            }
        );


        if (!response.ok) {
            throw new Error(
                "Failed to update habit"
            );
        }

        await rkRefreshRKOSData({ habits: true });

    } catch (error) {

        console.error(
            "RK OS: Failed to update habit:",
            error
        );

        await rkLoadHabits();

        alert(
            "Unable to update habit. Please try again."
        );
    }
}


async function rkDeleteHabit(habitId) {

    const confirmed =
        confirm("Delete this habit?");

    if (!confirmed) return;


    try {

        const response = await fetch(
            `/api/habits/${habitId}`,
            {
                method: "DELETE"
            }
        );


        if (!response.ok) {
            throw new Error(
                "Failed to delete habit"
            );
        }

        await rkRefreshRKOSData({ habits: true });

    } catch (error) {

        console.error(
            "RK OS: Failed to delete habit:",
            error
        );

        alert(
            "Unable to delete habit. Please try again."
        );
    }
}


/* ------------------------------------------------------------
   Enter key support
   ------------------------------------------------------------ */

document.addEventListener(
    "keydown",
    event => {

        const input =
            document.getElementById("habit-name");

        if (
            input &&
            document.activeElement === input &&
            event.key === "Enter"
        ) {

            event.preventDefault();

            rkAddHabit();
        }
    }
);