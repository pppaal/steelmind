"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { RobotState, SensorData } from "@/lib/types";
import { STATE_COLORS } from "@/lib/types";

interface Props {
  state: RobotState;
  sensor: SensorData | null;
}

interface Rig {
  group: THREE.Group;
  parts: THREE.Mesh[];
  joints: {
    hipLeft: THREE.Group;
    hipRight: THREE.Group;
    kneeLeft: THREE.Group;
    kneeRight: THREE.Group;
    shoulderLeft: THREE.Group;
    shoulderRight: THREE.Group;
  };
}

function buildRig(): Rig {
  const group = new THREE.Group();
  const parts: THREE.Mesh[] = [];
  const makeMat = () =>
    new THREE.MeshStandardMaterial({ color: STATE_COLORS.IDLE, metalness: 0.3, roughness: 0.5 });

  const torso = new THREE.Mesh(new THREE.BoxGeometry(0.7, 1.0, 0.4), makeMat());
  torso.position.y = 1.6;
  parts.push(torso);
  group.add(torso);

  const head = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.4, 0.4), makeMat());
  head.position.y = 2.35;
  parts.push(head);
  group.add(head);

  const makeLimbSegment = (
    parent: THREE.Object3D,
    pivot: THREE.Vector3,
    size: [number, number, number],
    offsetY: number,
  ): { joint: THREE.Group; mesh: THREE.Mesh } => {
    const joint = new THREE.Group();
    joint.position.copy(pivot);
    parent.add(joint);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), makeMat());
    mesh.position.y = offsetY;
    joint.add(mesh);
    parts.push(mesh);
    return { joint, mesh };
  };

  // Arms (shoulder pivots on torso)
  const shoulderLeft = makeLimbSegment(torso, new THREE.Vector3(0.45, 0.4, 0), [0.2, 0.8, 0.2], -0.4).joint;
  const shoulderRight = makeLimbSegment(torso, new THREE.Vector3(-0.45, 0.4, 0), [0.2, 0.8, 0.2], -0.4).joint;

  // Hips/legs (hip pivots at torso bottom, knees below)
  const hipLeftSeg = makeLimbSegment(torso, new THREE.Vector3(0.2, -0.5, 0), [0.25, 0.7, 0.25], -0.35);
  const hipRightSeg = makeLimbSegment(torso, new THREE.Vector3(-0.2, -0.5, 0), [0.25, 0.7, 0.25], -0.35);

  const kneeLeftSeg = makeLimbSegment(hipLeftSeg.joint, new THREE.Vector3(0, -0.7, 0), [0.22, 0.7, 0.22], -0.35);
  const kneeRightSeg = makeLimbSegment(hipRightSeg.joint, new THREE.Vector3(0, -0.7, 0), [0.22, 0.7, 0.22], -0.35);

  // Feet
  const footL = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.1, 0.45), makeMat());
  footL.position.set(0, -0.75, 0.08);
  kneeLeftSeg.joint.add(footL);
  parts.push(footL);
  const footR = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.1, 0.45), makeMat());
  footR.position.set(0, -0.75, 0.08);
  kneeRightSeg.joint.add(footR);
  parts.push(footR);

  return {
    group,
    parts,
    joints: {
      hipLeft: hipLeftSeg.joint,
      hipRight: hipRightSeg.joint,
      kneeLeft: kneeLeftSeg.joint,
      kneeRight: kneeRightSeg.joint,
      shoulderLeft,
      shoulderRight,
    },
  };
}

export default function RobotScene({ state, sensor }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef<RobotState>(state);
  const sensorRef = useRef<SensorData | null>(sensor);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);
  useEffect(() => {
    sensorRef.current = sensor;
  }, [sensor]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#0a0f1c");
    scene.fog = new THREE.Fog("#0a0f1c", 8, 24);

    const camera = new THREE.PerspectiveCamera(45, mount.clientWidth / mount.clientHeight, 0.1, 100);
    camera.position.set(3.5, 2.4, 4.5);
    camera.lookAt(0, 1.2, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const key = new THREE.DirectionalLight(0xffffff, 1.0);
    key.position.set(5, 8, 4);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x88aaff, 0.6);
    rim.position.set(-4, 3, -3);
    scene.add(rim);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(20, 20),
      new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.9 }),
    );
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);

    const grid = new THREE.GridHelper(20, 20, 0x1f2937, 0x1f2937);
    scene.add(grid);

    const rig = buildRig();
    scene.add(rig.group);

    const clock = new THREE.Clock();
    let frame = 0;
    const targetColor = new THREE.Color(STATE_COLORS.IDLE);

    const onResize = () => {
      if (!mount) return;
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    const animate = () => {
      frame = requestAnimationFrame(animate);
      const t = clock.getElapsedTime();
      const s = stateRef.current;

      targetColor.set(STATE_COLORS[s]);
      for (const mesh of rig.parts) {
        const mat = mesh.material as THREE.MeshStandardMaterial;
        mat.color.lerp(targetColor, 0.1);
      }

      const sd = sensorRef.current;
      const jp = sd?.joint_positions;
      const drive = s === "WALKING" ? 1 : s === "EXECUTING" ? 0.4 : 0;
      const fallbackHipL = drive * Math.sin(t * 4);
      const fallbackHipR = -drive * Math.sin(t * 4);
      const fallbackKneeL = drive * Math.max(0, Math.cos(t * 4));
      const fallbackKneeR = drive * Math.max(0, -Math.cos(t * 4));

      rig.joints.hipLeft.rotation.x = jp?.hip_left ?? fallbackHipL;
      rig.joints.hipRight.rotation.x = jp?.hip_right ?? fallbackHipR;
      rig.joints.kneeLeft.rotation.x = -Math.abs(jp?.knee_left ?? fallbackKneeL);
      rig.joints.kneeRight.rotation.x = -Math.abs(jp?.knee_right ?? fallbackKneeR);
      rig.joints.shoulderLeft.rotation.x = -(jp?.hip_left ?? fallbackHipL) * 0.6;
      rig.joints.shoulderRight.rotation.x = -(jp?.hip_right ?? fallbackHipR) * 0.6;

      if (sd?.imu_orientation) {
        rig.group.rotation.x = sd.imu_orientation.x * 0.3;
        rig.group.rotation.z = sd.imu_orientation.y * 0.3;
      }

      rig.group.position.y = s === "IDLE" ? -0.05 + Math.sin(t * 1.5) * 0.02 : 0;

      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      scene.traverse((obj) => {
        if ((obj as THREE.Mesh).geometry) (obj as THREE.Mesh).geometry.dispose();
        const mat = (obj as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else if (mat) mat.dispose();
      });
    };
  }, []);

  return <div ref={mountRef} className="h-full w-full" />;
}
