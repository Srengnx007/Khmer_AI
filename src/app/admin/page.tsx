"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useRouter } from "next/navigation";
import { db } from "@/lib/firebase";
import { collection, doc, updateDoc, deleteDoc, query, orderBy, onSnapshot } from "firebase/firestore";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Loader2, Trash2, Shield, ShieldOff, Search } from "lucide-react";
import { format } from "date-fns";

type UserData = {
    uid: string;
    name: string;
    email: string;
    role: "user" | "admin";
    provider: string;
    createdAt: any;
};

export default function AdminPage() {
    const { user, role, loading } = useAuth();
    const router = useRouter();
    const [users, setUsers] = useState<UserData[]>([]);
    const [searchTerm, setSearchTerm] = useState("");
    const [isLoadingUsers, setIsLoadingUsers] = useState(true);

    useEffect(() => {
        if (!loading) {
            if (!user) {
                router.push("/login");
            } else if (role !== "admin") {
                router.push("/dashboard");
            } else {
                // Real-time listener
                const usersRef = collection(db, "users");
                const q = query(usersRef, orderBy("createdAt", "desc"));

                const unsubscribe = onSnapshot(q, (snapshot) => {
                    const usersList = snapshot.docs.map((doc) => ({
                        uid: doc.id,
                        ...doc.data(),
                    })) as UserData[];
                    setUsers(usersList);
                    setIsLoadingUsers(false);
                }, (error) => {
                    console.error("Error fetching users:", error);
                    setIsLoadingUsers(false);
                });

                return () => unsubscribe();
            }
        }
    }, [user, role, loading, router]);

    const toggleRole = async (uid: string, currentRole: string) => {
        const newRole = currentRole === "admin" ? "user" : "admin";
        try {
            await updateDoc(doc(db, "users", uid), { role: newRole });
            setUsers(users.map(u => u.uid === uid ? { ...u, role: newRole } : u));
        } catch (error) {
            console.error("Error updating role:", error);
        }
    };

    const deleteUser = async (uid: string) => {
        if (!confirm("Are you sure you want to delete this user?")) return;
        try {
            await deleteDoc(doc(db, "users", uid));
            setUsers(users.filter(u => u.uid !== uid));
        } catch (error) {
            console.error("Error deleting user:", error);
        }
    };

    const filteredUsers = users.filter(u =>
        u.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        u.email.toLowerCase().includes(searchTerm.toLowerCase())
    );

    if (loading || (role === "admin" && isLoadingUsers)) {
        return (
            <div className="flex h-screen items-center justify-center">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
        );
    }

    if (role !== "admin") return null;

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <h1 className="text-3xl font-bold">Admin Dashboard</h1>
                <div className="relative w-64">
                    <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input
                        placeholder="Search users..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="pl-8"
                    />
                </div>
            </div>

            <Card>
                <CardHeader>
                    <CardTitle>User Management ({users.length})</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm text-left">
                            <thead className="text-xs uppercase bg-gray-50 dark:bg-gray-800">
                                <tr>
                                    <th className="px-6 py-3">User</th>
                                    <th className="px-6 py-3">Role</th>
                                    <th className="px-6 py-3">Provider</th>
                                    <th className="px-6 py-3">Joined</th>
                                    <th className="px-6 py-3">Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredUsers.map((user) => (
                                    <tr key={user.uid} className="border-b hover:bg-gray-50 dark:hover:bg-gray-800">
                                        <td className="px-6 py-4 font-medium">
                                            <div>{user.name}</div>
                                            <div className="text-xs text-muted-foreground">{user.email}</div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <span className={`px-2 py-1 rounded-full text-xs ${user.role === "admin"
                                                ? "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200"
                                                : "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200"
                                                }`}>
                                                {user.role}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 capitalize">{user.provider}</td>
                                        <td className="px-6 py-4">
                                            {user.createdAt?.seconds
                                                ? format(new Date(user.createdAt.seconds * 1000), "MMM d, yyyy")
                                                : "N/A"}
                                        </td>
                                        <td className="px-6 py-4 flex gap-2">
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => toggleRole(user.uid, user.role)}
                                                title={user.role === "admin" ? "Demote to User" : "Promote to Admin"}
                                            >
                                                {user.role === "admin" ? <ShieldOff className="h-4 w-4" /> : <Shield className="h-4 w-4" />}
                                            </Button>
                                            <Button
                                                variant="ghost"
                                                size="icon"
                                                className="text-red-500 hover:text-red-700"
                                                onClick={() => deleteUser(user.uid)}
                                                title="Delete User"
                                            >
                                                <Trash2 className="h-4 w-4" />
                                            </Button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}
